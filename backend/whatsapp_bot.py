"""Signed conversational WhatsApp adapter for the existing tenant rating engine.

No label is purchased from a message. Signed, expiring links open the authenticated
workspace, whose booking engine remains responsible for atomic wallet checks.
"""
import asyncio
import logging
import re
from decimal import Decimal
from typing import Any

import asyncpg
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from twilio.twiml.messaging_response import MessagingResponse

from backend.sandbox_hooks import authenticated_twilio_form

logger = logging.getLogger("easyinvio.whatsapp")
WEBHOOK_PATH = "/api/v1/integrations/whatsapp/webhook"


class WhatsAppConfiguration(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    twilio_account_sid: str = ""
    twilio_auth_token: SecretStr = SecretStr("")
    twilio_whatsapp_number: str = ""
    whatsapp_brand_name: str = "EasyInvio.com"


def initialize_whatsapp(configuration: Any = None) -> bool:
    """Report unmapped keys without exposing credentials or disabling other modules."""
    config = configuration if configuration is not None else WhatsAppConfiguration()
    token = config.twilio_auth_token
    token = token.get_secret_value() if isinstance(token, SecretStr) else str(token or "")
    number = config.twilio_whatsapp_number.removeprefix("whatsapp:")
    valid = bool(re.fullmatch(r"AC[0-9a-fA-F]{32}", config.twilio_account_sid)
                 and token and re.fullmatch(r"\+[1-9][0-9]{7,14}", number))
    if not valid:
        logger.warning("⚠️ EasyInvio.com Initialization Warning: Twilio environment configuration keys are unmapped.")
    return valid


def xml_message(text: str) -> str:
    response = MessagingResponse()
    # Long signed booking URLs can push three offers beyond Twilio's 1600
    # character limit. Split at line boundaries without corrupting a link.
    chunk = ""
    for line in text.split("\n"):
        if len(line) > 1590:
            raise ValueError("WhatsApp response line exceeds provider limit")
        candidate = chunk + "\n" + line if chunk else line
        if len(candidate) > 1590:
            response.message(chunk)
            chunk = line
        else:
            chunk = candidate
    if chunk:
        response.message(chunk)
    return str(response)


def format_quotes(brand: str, weight: Decimal, origin: str, destination: str,
                  offers: list[tuple[Any, str]], *, sandbox: bool, partial: bool,
                  wallet_blocked: bool) -> str:
    """Render only calibrated prices; never use floating point or invented offers."""
    heading = "Sandbox Quotes Found" if sandbox else "Live Quotes Found"
    lines = [f"📦 *{brand} {heading} ({weight:.2f}kg)*", f"Route: {origin} ➔ {destination}"]
    symbols = {"GBP": "£", "EUR": "€", "USD": "$"}
    for position, (rate, link) in enumerate(offers[:3]):
        lines.extend(["", f"{('1️⃣', '2️⃣', '3️⃣')[position]} *{rate.carrier_code} {rate.service_code}*",
                      f"    Price: *{symbols.get(rate.currency, '')}{rate.client_price_ex_tax:.2f} {rate.currency}*",
                      f"    🔗 _Book:_ {link}"])
    if not offers:
        lines.extend(["", "No carrier offers are available for this saved route."])
    lines.extend(["", "Prices exclude tax. Sign in to confirm the final total before booking."])
    if wallet_blocked:
        lines.extend(["", f"{brand} Alert: Your transaction was calculated successfully, but your wallet balance is too low to print labels. Please top up your profile online."])
    if partial:
        lines.extend(["", "Some providers did not return rates; available offers are shown."])
    if sandbox:
        lines.extend(["", "Sandbox only: this message does not purchase or print a carrier label."])
    return xml_message("\n".join(lines))


router = APIRouter(tags=["WhatsApp conversational logistics"])


@router.post(WEBHOOK_PATH)
async def whatsapp_webhook(request: Request) -> Response:
    settings = getattr(request.app.state, "settings", None)
    if settings is None or not settings.twilio_enabled:
        raise HTTPException(503, "Twilio integration is disabled")
    # Official RequestValidator uses the exact configured external HTTPS URL,
    # every form field, and the account's auth token; proxy headers are untrusted.
    form = await authenticated_twilio_form(request)
    service = request.app.state.whatsapp
    sender, receiver = form["From"].removeprefix("whatsapp:"), form["To"].removeprefix("whatsapp:")
    brand = getattr(settings, "whatsapp_brand_name", "EasyInvio.com")
    try:
        async with asyncio.timeout(settings.whatsapp_deadline_seconds):
            context = await service.resolve_sender(sender, receiver)
            if context is None:
                xml = xml_message(f"Welcome to {brand}. Your mobile number is not registered to an active workspace node. Please pair your mobile inside your online profile panel.")
            elif form["NumMedia"] != "0":
                xml = xml_message("Please send text: Quote 4.5kg from GB to US")
            else:
                xml = await service.process(context, form["MessageSid"], form["Body"], sender,
                                            conversational=True)
    except TimeoutError:
        xml = xml_message("The carriers did not respond quickly enough. Please resend shortly.")
    except HTTPException as exc:
        xml = xml_message("Rates are temporarily unavailable. Please try again." if exc.status_code == 503
                          else "This quote could not be processed. Contact your workspace admin.")
    except (ValueError, ValidationError, asyncpg.PostgresError):
        logger.error("WhatsApp saved-route or database processing failed")
        xml = xml_message("Ask your workspace admin to check the saved route and carrier configuration.")
    return Response(content=xml, media_type="application/xml")
