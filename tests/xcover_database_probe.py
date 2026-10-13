"""Rolled-back SANDBOX accounting and private claims; no external API calls."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import asyncpg
import httpx
from fastapi import FastAPI
from PIL import Image

import main
from backend.admin_portal import authenticate_platform_owner
from backend.automation_three_partners import BookingRequest, PartnerLifecycleService
from backend.shipment_protection import ProtectionService, XCoverClient, build_router
from test_xcover_protection import settings as controlled_settings, native_headers
from test_xclaim import claim_settings
from backend.xcover_claims import XClaimClient, XClaimService
import hashlib
import hmac


async def run():
    config = main.Settings()
    assert (
        config.database_environment == "SANDBOX"
        and config.provider_environment == "TEST"
    )
    db = await asyncpg.connect(
        config.database_url.get_secret_value(),
        timeout=15,
        ssl=main.database_tls_context(
            config.database_ca_file, strict=config.database_tls_strict
        ),
    )
    transaction = db.transaction()
    await transaction.start()
    report = {
        "database": "Supabase SANDBOX",
        "external_api_calls": 0,
        "messages_sent": 0,
        "migration_persisted": False,
        "checks": [],
    }

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield db

    try:
        migration = Path("migrations/033_xcover_claim_cases.sql").read_text(
            encoding="utf-8"
        )
        migration = "\n".join(
            line
            for line in migration.splitlines()
            if line.strip() not in {"BEGIN;", "COMMIT;"}
        )
        await db.execute(migration)
        # Rerunning within the test verifies idempotent schema upgrades.
        await db.execute(migration)
        report["checks"].append(
            "PASS: migration syntax, constraints and second-run idempotence"
        )
        tenant = await db.fetchval(
            "SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-03' AND is_sandbox"
        )
        actor = await db.fetchrow(
            "SELECT id,auth_user_id FROM public.users WHERE tenant_id=$1 AND is_active AND role='OWNER' LIMIT 1",
            tenant,
        )
        assert actor and actor["auth_user_id"]
        context = main.TenantContext(tenant, actor["auth_user_id"], "OWNER", "")
        await db.execute(
            "UPDATE public.tenants SET billing_plan='PREPAID_WALLET',workspace_status='ACTIVE',billing_status='ACTIVE',default_currency='GBP' WHERE tenant_id=$1",
            tenant,
        )
        await db.execute(
            "UPDATE public.wallets SET balance=100,reserved_balance=0,currency='GBP' WHERE tenant_id=$1",
            tenant,
        )
        pool = Pool()
        finance = main.FinanceEngine(pool, config, None)
        source = await db.fetchval(
            "SELECT to_jsonb(s) FROM public.shipments s WHERE customer_reference='SEED24-3-2'"
        )
        source = json.loads(source) if isinstance(source, str) else source
        columns = await db.fetchval(
            "SELECT string_agg(quote_ident(attname),',' ORDER BY attnum) FROM pg_attribute WHERE attrelid='public.shipments'::regclass AND attnum>0 AND NOT attisdropped AND attgenerated=''"
        )
        policies = {}
        calls = []
        outcomes = {}
        quote_ids = {}
        native_claims = {}
        native_types = uuid4()
        native_file = uuid4()

        def transport(request):
            calls.append((request.method, request.url.path))
            if request.url.host == "api.xclaim.xcover-staging.com":
                path = request.url.path
                if "/auth/jwt/" in path:
                    return httpx.Response(
                        200,
                        json={
                            "data": {
                                "jwt": "synthetic.synthetic.synthetic",
                                "expiresIn": 60,
                            }
                        },
                    )
                if path.endswith("/claim-types"):
                    return httpx.Response(
                        200,
                        json={
                            "data": [
                                {"id": str(native_types), "name": "parcel_damaged"}
                            ]
                        },
                    )
                if "/fnol/" in path:
                    return httpx.Response(
                        200,
                        json={
                            "data": {
                                "sections": [
                                    {
                                        "name": "claim_information",
                                        "sectionFields": [
                                            {
                                                "name": "description",
                                                "type": "string",
                                                "required": True,
                                            }
                                        ],
                                    },
                                    {
                                        "name": "evidence",
                                        "sectionFields": [
                                            {
                                                "name": "photos",
                                                "type": "file",
                                                "required": True,
                                            }
                                        ],
                                    },
                                ]
                            }
                        },
                    )
                if path.endswith("/files"):
                    return httpx.Response(201, json={"data": {"id": str(native_file)}})
                if request.method == "POST":
                    data = json.loads(request.content)
                    assert data["sectionFields"]["evidence:photos"]["value"] == [
                        str(native_file)
                    ]
                    assert data["claimantSection"]["email"] == "qa@example.test"
                    ref = "NATIVE-" + uuid4().hex + "-CLA"
                    cid = str(uuid4())
                    native_claims[ref] = {
                        "id": cid,
                        "bookingReference": data["bookingReference"],
                        "quoteReference": data["quoteReference"],
                        "status": {"category": "Under Assessment"},
                    }
                    return httpx.Response(202, json={"data": {"claim_reference": ref}})
                ref = path.rsplit("/", 1)[-1]
                claim = native_claims.get(ref) or next(
                    value for value in native_claims.values() if value["id"] == ref
                )
                return httpx.Response(200, json={"data": claim})
            assert request.url.host == "staging.api.xcover.com"
            if request.method == "POST" and request.url.path.endswith("/quotes/"):
                body = json.loads(request.content)
                sid = body["partner_transaction_id"]
                package = "QA-" + sid.replace("-", "") + "-INS"
                qid = str(uuid4())
                quote_ids[package] = qid
                return httpx.Response(
                    201,
                    json={
                        "id": package,
                        "currency": "GBP",
                        "total_price": "1.44",
                        "quotes": [
                            {
                                "id": qid,
                                "tax": {
                                    "total_tax": "0.24",
                                    "total_amount_without_tax": "1.20",
                                },
                                "cover_amount": "100.00",
                                "policy": {"policy_type": "parcel_insurance"},
                                "commission": {"total_commission": "0.40"},
                                "pds_url": "https://www.xcover.com/en/pds/qa-only",
                            }
                        ],
                    },
                )
            package = request.url.path.rstrip("/").rsplit("/", 1)[-1]
            if request.method == "POST":
                body = json.loads(request.content)
                sid = body["partner_transaction_id"]
                booking = {
                    "id": package,
                    "currency": "GBP",
                    "status": "CONFIRMED",
                    "total_price": "1.44",
                    "total_tax": "0.24",
                    "partner_transaction_id": sid,
                    "quotes": [
                        {
                            "id": quote_ids[package],
                            "status": "CONFIRMED",
                            "policy": {"policy_type": "parcel_insurance"},
                        }
                    ],
                    "fnol_link": "https://www.xcover.com/claims/qa-only",
                }
                if outcomes.get(sid) == "reject":
                    return httpx.Response(422, json={"code": "controlled-rejection"})
                policies[package] = booking
                if outcomes.get(sid) == "timeout":
                    raise httpx.ReadTimeout("Controlled post timeout", request=request)
                return httpx.Response(200, json=booking)
            return httpx.Response(200, json=policies[package])

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            provider = XCoverClient(http, controlled_settings())
            protection = ProtectionService(pool, provider, finance)

            class LabelLifecycle:
                async def confirm(self, user, body):
                    offer = await db.fetchrow(
                        "SELECT shipment_id FROM public.partner_shipping_offers WHERE tenant_id=$1 AND offer_id=$2",
                        user.tenant_id,
                        body.offer_id,
                    )
                    permit = await finance.reserve(user, offer["shipment_id"])
                    await finance.mark_submitted(permit, verified_test_environment=True)
                    label = {
                        "tracking_number": "XCOVER-QA-" + str(offer["shipment_id"]),
                        "label_url": "https://label.example.invalid/qa.pdf",
                    }
                    await finance.finish_booking(
                        permit,
                        "SUCCESS",
                        tracking_number=label["tracking_number"],
                        label_storage_path=label["label_url"],
                        label_documents=label,
                        verified_test_environment=True,
                    )
                    return {
                        "shipment_id": str(offer["shipment_id"]),
                        "status": "BOOKED",
                        "label": label,
                    }

                public_result = PartnerLifecycleService.public_result

            lifecycle = LabelLifecycle()

            async def fixture(outcome):
                sid, offer = uuid4(), uuid4()
                outcomes[str(sid)] = outcome
                address = {
                    "name": "Synthetic QA",
                    "line1": "1 Test Road",
                    "city": "Leeds",
                    "postal_code": "LS1 1AA",
                    "country_code": "GB",
                    "email": "qa@example.test",
                }
                order = {
                    "origin": address,
                    "destination": address,
                    "currency": "GBP",
                    "customs_currency": "GBP",
                    "items": [
                        {
                            "description": "Synthetic test goods",
                            "unit_value": "100.00",
                            "quantity": 1,
                            "unit_weight_kg": "1.000",
                            "origin_country": "GB",
                        }
                    ],
                }
                rate = {
                    "client_price_ex_tax": "10.00",
                    "currency": "GBP",
                    "carrier_code": "DPD",
                    "offer_id": str(offer),
                }
                data = dict(
                    source,
                    id=str(sid),
                    tenant_id=str(tenant),
                    created_by_user_id=str(actor["id"]),
                    idempotency_key=str(uuid4()),
                    customer_reference="XCOVER-QA-" + sid.hex,
                    status="QUOTED",
                    currency="GBP",
                    wholesale_cost="8.00",
                    profit_markup="2.00",
                    tax_amount="0.00",
                    tracking_number=None,
                    booked_at=None,
                    dispatched_at=None,
                    delivered_at=None,
                    last_tracking_event_at=None,
                    label_storage_path=None,
                    quote_expires_at=(
                        datetime.now(timezone.utc) + timedelta(hours=1)
                    ).isoformat(),
                    ecommerce_store_id=None,
                    store_order_id=None,
                    pricing_snapshot={
                        "markup_type": "MANUAL",
                        "markup_value": "2.00",
                        "currency": "GBP",
                        "selected_rate": rate,
                    },
                    logistics_metadata={
                        "fixture_batch": "xcover-rollback-probe",
                        "automation_order": order,
                    },
                )
                await db.execute(
                    f"INSERT INTO public.shipments({columns}) SELECT {columns} FROM jsonb_populate_record(NULL::public.shipments,$1)",
                    json.dumps(data),
                )
                await db.execute(
                    "INSERT INTO public.partner_shipping_offers(tenant_id,offer_id,shipment_id,rate_snapshot,expires_at) VALUES($1,$2,$3,$4::jsonb,$5)",
                    tenant,
                    offer,
                    sid,
                    json.dumps(rate),
                    datetime.now(timezone.utc) + timedelta(hours=1),
                )
                prepared = await protection.prepare(context, offer)
                return sid, offer, prepared

            sid, offer, quote_data = await fixture("success")
            body = BookingRequest(
                tenant_id=tenant,
                offer_id=offer,
                insurance_requested=True,
                insurance_quote_id=UUID(quote_data["insurance_quote_id"]),
                insurance_terms_accepted=True,
            )
            result = await protection.confirm(context, body, lifecycle)
            assert result["insurance"]["insured"]
            wallet = await db.fetchrow(
                "SELECT balance,reserved_balance FROM public.wallets WHERE tenant_id=$1",
                tenant,
            )
            assert (
                wallet["balance"] == Decimal("88.56")
                and wallet["reserved_balance"] == 0
            )
            before = len(calls)
            assert (await protection.confirm(context, body, lifecycle))["insurance"][
                "insured"
            ]
            assert len(calls) == before
            assert (
                await db.fetchval(
                    "SELECT count(*) FROM public.wallet_ledger WHERE tenant_id=$1 AND insurance_purchase_id=$2 AND entry_type='INSURANCE_CAPTURE'",
                    tenant,
                    UUID(quote_data["insurance_quote_id"]),
                )
                == 1
            )
            report["checks"].append(
                "PASS: label + actual premium/tax wallet capture, immutable quote consent and idempotent insured retry"
            )
            app = FastAPI()
            app.state.xcover = provider
            app.state.protection = protection
            app.state.finance = finance

            async def auth():
                return context

            async def owner():
                return SimpleNamespace(user_id=context.user_id)

            app.include_router(build_router(auth))
            app.dependency_overrides[authenticate_platform_owner] = owner
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://qa"
            ) as web:
                image = BytesIO()
                Image.new("RGB", (4, 4)).save(image, format="PNG")
                case_id = uuid4()
                payload = {
                    "shipment_id": str(sid),
                    "claim_id": str(case_id),
                    "reason": "PARCEL_DAMAGED",
                    "notes": "Synthetic damaged goods evidence only.",
                }
                response = await web.post(
                    "/api/v1/shipping/submit-claim",
                    data=payload,
                    files={"photos": ("qa.png", image.getvalue(), "image/png")},
                )
                assert response.status_code == 200, response.text
                assert (
                    response.json()["status"] == "CLAIM_INGESTED"
                    and not response.json()["insurer_submission_confirmed"]
                )
                duplicate = await web.post(
                    "/api/v1/shipping/submit-claim",
                    data=payload,
                    files={"photos": ("qa.png", image.getvalue(), "image/png")},
                )
                assert duplicate.status_code == 200, duplicate.text
                assert (
                    await db.fetchval(
                        "SELECT count(*) FROM public.insurance_claim_evidence WHERE tenant_id=$1 AND case_id=$2",
                        tenant,
                        case_id,
                    )
                    == 1
                )
                forged = await web.post(
                    "/api/v1/shipping/insurance-updates",
                    headers=native_headers(provider.settings),
                    json={"event": "APPROVED", "amount": "5000"},
                )
                assert forged.status_code == 422
                update = {
                    "event": "BOOKING_CANCELLED",
                    "payload": {
                        "id": result["insurance"]["policy_id"],
                        "status": "CANCELLED",
                    },
                }
                first = await web.post(
                    "/api/v1/shipping/insurance-updates",
                    headers=native_headers(provider.settings),
                    json=update,
                )
                second = await web.post(
                    "/api/v1/shipping/insurance-updates",
                    headers=native_headers(provider.settings),
                    json=update,
                )
                assert (
                    first.status_code == 200 and second.json()["duplicate"]
                ), first.text
                assert (
                    first.json()["verified_policy_status"] == "CONFIRMED"
                    and not first.json()["wallet_credit"]
                )
                settlement = {
                    "tenant_id": str(tenant),
                    "claim_id": str(case_id),
                    "settlement_id": str(uuid4()),
                    "approved_amount": "75.00",
                    "currency": "GBP",
                    "insurer_payment_reference": "QA-RECEIVED-" + uuid4().hex,
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "funds_received_verified": True,
                }
                credit = await web.post(
                    "/api/v1/admin/insurance/settlements", json=settlement
                )
                assert credit.status_code == 200, credit.text
                duplicate = await web.post(
                    "/api/v1/admin/insurance/settlements", json=settlement
                )
                assert (
                    duplicate.status_code == 200 and duplicate.json()["duplicate"]
                ), duplicate.text
                assert await db.fetchval(
                    "SELECT balance FROM public.wallets WHERE tenant_id=$1", tenant
                ) == Decimal("163.56")
                assert (
                    await web.get("/api/v1/shipping/claims/" + str(case_id))
                ).json()["wallet_credit"]
                settlement["approved_amount"] = "76.00"
                assert (
                    await web.post(
                        "/api/v1/admin/insurance/settlements", json=settlement
                    )
                ).status_code == 409
                second_case = uuid4()
                payload["claim_id"] = str(second_case)
                assert (
                    await web.post("/api/v1/shipping/submit-claim", data=payload)
                ).status_code == 200
                settlement.update(
                    claim_id=str(second_case),
                    settlement_id=str(uuid4()),
                    approved_amount="50.00",
                    insurer_payment_reference="QA-OTHER-" + uuid4().hex,
                )
                assert (
                    await web.post(
                        "/api/v1/admin/insurance/settlements", json=settlement
                    )
                ).status_code == 409
                assert await db.fetchval(
                    "SELECT balance FROM public.wallets WHERE tenant_id=$1", tenant
                ) == Decimal("163.56")
            report["checks"].append(
                "PASS: private photo/case idempotence, portal referral, authoritative GET webhook verification, unsupported approval rejection and one-time approved-amount operator payout"
            )
            for outcome in ["timeout", "reject"]:
                sid, offer, quote_data = await fixture(outcome)
                body = BookingRequest(
                    tenant_id=tenant,
                    offer_id=offer,
                    insurance_requested=True,
                    insurance_quote_id=UUID(quote_data["insurance_quote_id"]),
                    insurance_terms_accepted=True,
                )
                before = await db.fetchval(
                    "SELECT balance FROM public.wallets WHERE tenant_id=$1", tenant
                )
                result = await protection.confirm(context, body, lifecycle)
                assert not result["insurance"]["insured"]
                assert (
                    await db.fetchval(
                        "SELECT balance FROM public.wallets WHERE tenant_id=$1", tenant
                    )
                    == before - 10
                )
                reserved = await db.fetchval(
                    "SELECT reserved_balance FROM public.wallets WHERE tenant_id=$1",
                    tenant,
                )
                assert reserved == (Decimal("1.44") if outcome == "timeout" else 0)
                if outcome == "timeout":
                    posts = sum(
                        method == "POST" and "/bookings/" in path
                        for method, path in calls
                    )
                    assert await protection.reconcile_pending() == 1
                    assert (
                        sum(
                            method == "POST" and "/bookings/" in path
                            for method, path in calls
                        )
                        == posts
                    )
                    assert (
                        await db.fetchval(
                            "SELECT reserved_balance FROM public.wallets WHERE tenant_id=$1",
                            tenant,
                        )
                        == 0
                    )
            report["checks"].append(
                "PASS: policy timeout retains reservation and reconciles via GET without second POST; definitive rejection releases only the protection reserve"
            )
            native_config = claim_settings().model_copy(
                update={
                    "claims_settlement_mapping": {
                        name: "/qaSettlement/" + name
                        for name in [
                            "amount",
                            "currency",
                            "payment_reference",
                            "payee",
                            "funds_received",
                            "received_at",
                        ]
                    },
                    "claims_master_payee_id": "SYNTHETIC-MASTER",
                }
            )
            native = XClaimService(pool, XClaimClient(http, native_config), protection)
            app.state.claims = native
            sid, offer, quote_data = await fixture("success")
            body = BookingRequest(
                tenant_id=tenant,
                offer_id=offer,
                insurance_requested=True,
                insurance_quote_id=UUID(quote_data["insurance_quote_id"]),
                insurance_terms_accepted=True,
            )
            await protection.confirm(context, body, lifecycle)
            native_case = uuid4()
            baseline = await db.fetchval(
                "SELECT balance FROM public.wallets WHERE tenant_id=$1", tenant
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://qa"
            ) as web:
                payload = {
                    "shipment_id": str(sid),
                    "claim_id": str(native_case),
                    "reason": "PARCEL_DAMAGED",
                    "notes": "Controlled native claim evidence.",
                }
                response = await web.post(
                    "/api/v1/shipping/submit-claim",
                    data=payload,
                    files={"photos": ("qa.png", image.getvalue(), "image/png")},
                )
                assert (
                    response.status_code == 200
                    and response.json()["status"] == "SUBMISSION_PENDING"
                ), response.text
                await native.drain()
                before = sum(
                    method == "POST" and path.endswith("/claims")
                    for method, path in calls
                )
                await native.drain()
                assert (
                    sum(
                        method == "POST" and path.endswith("/claims")
                        for method, path in calls
                    )
                    == before
                )
                record = await db.fetchrow(
                    "SELECT upstream_claim_id,upstream_claim_reference,state FROM public.insurance_claim_cases WHERE tenant_id=$1 AND id=$2",
                    tenant,
                    native_case,
                )
                assert record["state"] == "UNDER_INSURER_REVIEW"
                update = {
                    "event": "claim.status-category-update",
                    "payload": {
                        "id": str(record["upstream_claim_id"]),
                        "claimReference": record["upstream_claim_reference"],
                        "status": {"category": "Payment Complete"},
                        "amount": "5000",
                    },
                }
                raw = json.dumps(update).encode()
                signature = (
                    "sha256="
                    + hmac.new(
                        native_config.claims_webhook_secret.get_secret_value().encode(),
                        raw,
                        hashlib.sha256,
                    ).hexdigest()
                )
                forged = await web.post(
                    "/api/v1/shipping/insurance-updates",
                    content=raw,
                    headers={"XClaim-Signature": "sha256=invalid"},
                )
                assert forged.status_code == 401
                valid = await web.post(
                    "/api/v1/shipping/insurance-updates",
                    content=raw,
                    headers={"XClaim-Signature": signature},
                )
                assert (
                    valid.status_code == 200 and not valid.json()["wallet_credit"]
                ), valid.text
                assert (
                    await db.fetchval(
                        "SELECT balance FROM public.wallets WHERE tenant_id=$1", tenant
                    )
                    == baseline
                )
                claim = native_claims[record["upstream_claim_reference"]]
                claim["status"]["category"] = "Payment Complete"
                claim["qaSettlement"] = {
                    "amount": "40.00",
                    "currency": "GBP",
                    "payment_reference": "QA-NATIVE-" + uuid4().hex,
                    "payee": "SYNTHETIC-MASTER",
                    "funds_received": True,
                    "received_at": datetime.now(timezone.utc).isoformat(),
                }
                paid = await web.post(
                    "/api/v1/shipping/insurance-updates",
                    content=raw,
                    headers={"XClaim-Signature": signature},
                )
                assert (
                    paid.status_code == 200 and paid.json()["wallet_credit"]
                ), paid.text
                repeat = await web.post(
                    "/api/v1/shipping/insurance-updates",
                    content=raw,
                    headers={"XClaim-Signature": signature},
                )
                assert (
                    repeat.status_code == 200 and repeat.json()["duplicate"]
                ), repeat.text
                assert (
                    await db.fetchval(
                        "SELECT balance FROM public.wallets WHERE tenant_id=$1", tenant
                    )
                    == baseline + 40
                )
                assert (
                    await db.fetchval(
                        "SELECT verification_source FROM public.insurance_settlements WHERE tenant_id=$1 AND case_id=$2",
                        tenant,
                        native_case,
                    )
                    == "XCLAIM_API"
                )
            report["checks"].append(
                "PASS: native JWT/FNOL/photo upload/async claim fence, truthful assessment state, forged and stale status rejection, authoritative master-payee receipt and idempotent approved-amount credit from a partner-specific synthetic payout fixture"
            )
        report["status"] = "PASS"
    finally:
        await transaction.rollback()
        await db.close()
        report["all_database_writes_rolled_back"] = True
    target = Path("output/protection/xcover_database_probe.json")
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(run())
