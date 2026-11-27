"""Explainable logistics predictions and route history.

Predictions are suggestions, not certified tariff classifications. No external
AI service receives shipment descriptions. Currency and confidence use Decimal.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Annotated, Any, Callable, Literal
from uuid import UUID

import asyncpg
import pycountry
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from types import SimpleNamespace
from pydantic import BaseModel, ConfigDict, Field, field_validator


CENT = Decimal("0.01")


def strict_decimal(value: Any) -> Decimal:
    if isinstance(value, (float, bool)):
        raise ValueError("Use decimal strings, not floating-point numbers")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('A valid finite decimal is required') from None
    if not result.is_finite():
        raise ValueError("A finite decimal is required")
    return result


def amount(value: Decimal) -> str:
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def country_code(value: str) -> str:
    value = value.strip().upper()
    record = pycountry.countries.get(alpha_2=value) if len(value) == 2 else pycountry.countries.get(alpha_3=value)
    if record is None:
        raise ValueError("Use a valid ISO country code")
    return record.alpha_2


@dataclass(frozen=True)
class CommodityRule:
    code: str
    title: str
    pattern: str
    required: tuple[str, ...]
    assumptions: str


# Small curated mock classifier. Six-digit HS headings; national extensions
# and tariff-year applicability must be reviewed by a customs specialist.
COMMODITIES = (
    CommodityRule("640411", "Sports/training footwear with textile uppers", r"\b(sneakers?|trainers?|running shoes?)\b", ("textile", "silk", "cotton", "fabric"), "Assumes qualifying sports/training footwear, textile upper and rubber/plastic outer sole; leather trim alone does not determine upper material."),
    CommodityRule("640399", "Other footwear with leather uppers", r"\b(shoes?|sneakers?|boots?)\b", ("leather",), "Assumes leather upper and rubber/plastic/leather outer sole; construction and ankle coverage require review."),
    CommodityRule("610910", "Cotton knitted T-shirts", r"\b(t[ -]?shirts?|tees?)\b", ("cotton",), "Assumes knitted/crocheted cotton garment, rather than woven fabric."),
    CommodityRule("420222", "Handbags with plastic sheeting or textile outer surface", r"\b(handbags?|purses?)\b", ("textile", "fabric", "plastic"), "Assumes handbag and qualifying outer surface; leather bags need a different classification."),
    CommodityRule("847130", "Portable automatic data-processing machines", r"\b(laptops?|notebooks?)\b", ("computer", "laptop"), "Assumes portable computer weighing no more than 10 kg with CPU, keyboard and display."),
    CommodityRule("851713", "Smartphones", r"\b(smartphones?|iphone|android phone)\b", ("smartphone", "iphone", "android"), "Assumes complete smartphone under HS 2022; destination tariff version requires review."),
    CommodityRule("691200", "Non-porcelain ceramic household articles", r"\b(mugs?|cups?|plates?)\b", ("ceramic", "stoneware"), "Assumes non-porcelain/non-china ceramic tableware."),
    CommodityRule("950300", "Toys", r"\b(toys?|teddy bears?|building blocks)\b", ("toy", "teddy", "blocks"), "Assumes article intended as a toy; age, function and exclusions require review."),
)


def predict_hs_code(item_description: str) -> dict:
    if not isinstance(item_description, str):
        raise ValueError("Description must be text")
    text = re.sub(r"\s+", " ", item_description.strip().lower())
    if not 3 <= len(text) <= 500 or any(ord(char) < 32 for char in text):
        raise ValueError("Enter 3–500 characters without control characters")
    text = re.sub(r'\bfootwear\b', 'shoes', text)
    if 'cotton' in text and ('knitted' in text or 'knit' in text):
        text = re.sub(r'\bgarments?\b', 't-shirt', text)
    candidates = []
    for rule in COMMODITIES:
        if re.search(rule.pattern, text):
            terms = [term for term in rule.required if re.search(r"\b" + re.escape(term) + r"\b", text)]
            score = Decimal("0.58") + min(Decimal("0.24"), Decimal(len(terms)) * Decimal("0.12"))
            # A mention of leather trim must not outweigh explicit textile upper.
            if rule.code == "640399" and "trim" in text:
                score -= Decimal("0.15")
            candidates.append({"hs_code": rule.code, "title": rule.title, "confidence": amount(score), "matched_terms": terms, "assumptions": rule.assumptions})
    candidates.sort(key=lambda row: (-Decimal(row["confidence"]), row["hs_code"]))
    best = candidates[0] if candidates else None
    return {"description": item_description.strip(), "hs_code": best["hs_code"] if best else None,
            "confidence": best["confidence"] if best else "0.00", "candidates": candidates,
            "status": "review_required" if best else "insufficient_information",
            "simulated": True, "model": "explainable-rules-v1", "tariff_version": "HS-2022",
            "notice": "Simulated confidence, not a calibrated probability. Confirm material, construction, intended use and destination tariff before declaration."}


def analyze_tracking_history(origin: str, destination: str, observations: list[dict], *, simulated: bool = False) -> dict:
    origin, destination = country_code(origin), country_code(destination)
    summaries = []
    for provider in ("EASYPOST", "REGIONAL"):
        active_exceptions = sum(row.get('provider') == provider and row.get('active_exception') is True for row in observations)
        delays = []
        for row in observations:
            if row.get("provider") != provider:
                continue
            try:
                days = strict_decimal(row["delay_days"])
                if Decimal("0") <= days <= Decimal("365"):
                    delays.append(days)
            except (ValueError, ArithmeticError, KeyError):
                continue
        if not delays:
            summaries.append({"provider": provider, "sample_size": 0, "risk": "high" if active_exceptions else "unknown", "active_exceptions": active_exceptions, "mean_delay_days": None, "late_ratio": None, "anomaly_count": 0})
            continue
        mean = sum(delays, Decimal("0")) / len(delays)
        variance = sum(((delay - mean) ** 2 for delay in delays), Decimal("0")) / len(delays)
        threshold = mean + Decimal("2") * variance.sqrt()
        late_ratio = Decimal(sum(delay >= 2 for delay in delays)) / len(delays)
        risk = "high" if mean >= 3 or late_ratio >= Decimal("0.5") else "moderate" if mean >= 1 else "low"
        summaries.append({"provider": provider, "sample_size": len(delays), "active_exceptions": active_exceptions, "risk": "high" if active_exceptions else risk if len(delays) >= 5 else "insufficient_history",
                          "mean_delay_days": amount(mean), "late_ratio": amount(late_ratio),
                          "anomaly_count": sum(delay > threshold for delay in delays), "anomaly_threshold_days": amount(threshold)})
    ranked = sorted((row for row in summaries if row["sample_size"] >= 5), key=lambda row: Decimal(row["mean_delay_days"]))
    return {"origin": origin, "destination": destination, "providers": summaries,
            "recommended_provider": ranked[0]["provider"] if ranked else None,
            "simulated": simulated, "source": "fixture_history" if simulated else "shipment_tracking_history",
            "notice": "Historical delays are advisory and do not guarantee future delivery. At least five observations are required per provider."}


def evaluate_carrier_disruptions(origin: str, destination: str) -> dict:
    """Deterministic mock framework; live route below reads tenant history."""
    observations = ([{"provider": "EASYPOST", "delay_days": str(value)} for value in (0, 0, 1, 0, 2, 0, 1, 0)] +
                    [{"provider": "REGIONAL", "delay_days": str(value)} for value in (0, 1, 3, 4, 2, 5, 0, 8)])
    return analyze_tracking_history(origin, destination, observations, simulated=True)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DescriptionInput(StrictModel):
    item_description: str = Field(min_length=3, max_length=500)


def build_router(authenticate: Callable) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Logistics predictions"])
    from backend.admin_portal import authenticate_platform_owner

    @router.post("/customs/harmonize")
    async def harmonize(body: DescriptionInput,request:Request,context:Any=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN','DISPATCHER'}:raise HTTPException(403,'Dispatch permission required')
        from backend.entitlements import guard_feature
        await guard_feature(request.app.state.finance.pool,request.app.state.settings,context.tenant_id,'customs_hs_builder')
        try:
            return predict_hs_code(body.item_description)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.get("/routing/disruptions")
    async def routing(origin: str, destination: str, request: Request, context: Any = Depends(authenticate)):
        try:
            origin, destination = country_code(origin), country_code(destination)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        from backend.carrier_consolidation import route_history
        try:
            history=await route_history(request.app.state.finance.pool,context.tenant_id,destination,origin)
        except (asyncpg.PostgresError,ValueError):
            raise HTTPException(503,'Carrier route history unavailable') from None
        return {'carriers':[{'carrier_code':carrier,**{key:str(value) if isinstance(value,Decimal) else value for key,value in stats.items()}} for carrier,stats in history.items()],
            'source':'tenant shipment history','window_days':90,'origin_filter_applied':True,
            'notice':'Carrier/destination history for your workspace; synthetic fixtures excluded.'}

    return router
