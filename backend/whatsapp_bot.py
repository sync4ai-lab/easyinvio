"""Signed WhatsApp ingress into the shared authenticated conversational gateway.

Booking commands return a signed selection link to authenticated web checkout.
Payment and label purchase require confirmation in the workspace.
"""
import logging
import re
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from twilio.twiml.messaging_response import MessagingResponse

logger = logging.getLogger("easyinvio.whatsapp")
WEBHOOK_PATH = "/api/v1/integrations/whatsapp/webhook"


from backend.whatsapp_provider import WhatsAppProviderSettings

class WhatsAppConfiguration(WhatsAppProviderSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    twilio_account_sid: str = ""
    twilio_auth_token: SecretStr = SecretStr("")
    twilio_whatsapp_number: str = ""
    whatsapp_brand_name: str = "EasyInvio.com"


def initialize_whatsapp(configuration: Any = None) -> bool:
    """Report unmapped keys without exposing credentials or disabling other modules."""
    config = configuration if configuration is not None else WhatsAppConfiguration()
    from backend.whatsapp_provider import provider,enabled
    if provider(config)=='GUPSHUP':return enabled(config)
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
                      f"    🔗 _Book:_ {link}" if link else "    Book in your signed-in EasyInvio workspace."])
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
    from backend.whatsapp_queue import accept_whatsapp
    return await accept_whatsapp(request)
