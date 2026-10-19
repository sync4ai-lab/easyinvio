"""Query-secret redaction and optional trusted-proxy-aware webhook IP policy."""
import ipaddress
import logging
import os
import re
import traceback

from fastapi import HTTPException


def redact_query_secrets(value):
    # Also covers escaped/percent-encoded separators in HTTP library tracebacks.
    return re.sub(r'(?i)((?:[?&]|%3f|%26)(?:token|access_token)(?:=|%3d))[^\s&#"\'<>]+',
                  r'\1[REDACTED]', str(value))


class WebhookSecretFilter(logging.Filter):
    def filter(self, record):
        if record.name == 'uvicorn.access' and isinstance(record.args, tuple) and len(record.args) == 5:
            # AccessFormatter requires all five original fields, including the
            # numeric status. Redact the URL without destroying that contract.
            record.msg = redact_query_secrets(record.msg)
            record.args = tuple(redact_query_secrets(value) if isinstance(value, str) else value
                                for value in record.args)
        else:
            record.msg = redact_query_secrets(record.getMessage())
            record.args = ()
            # Uvicorn's colour formatter otherwise substitutes its original
            # template after formatting args have already been consumed.
            record.__dict__.pop('color_message', None)
        if record.exc_info:
            record.exc_text = redact_query_secrets(''.join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact_query_secrets(record.exc_text)
        if record.stack_info:
            record.stack_info = redact_query_secrets(record.stack_info)
        return True


def install_webhook_log_redaction():
    """Protect configured application and HTTP/access handlers at startup."""
    for name in ('', 'veloce', 'httpx', 'httpcore', 'uvicorn', 'uvicorn.error', 'uvicorn.access'):
        logger = logging.getLogger(name)
        if not any(isinstance(item, WebhookSecretFilter) for item in logger.filters):
            logger.addFilter(WebhookSecretFilter())
        for handler in logger.handlers:
            if not any(isinstance(item, WebhookSecretFilter) for item in handler.filters):
                handler.addFilter(WebhookSecretFilter())


def enforce_shippo_source_ip(request):
    """Opt-in allowlist, using the socket peer unless explicit proxies are trusted.

    Deployment must disable automatic ASGI proxy-header rewriting; otherwise
    the socket peer has already been replaced before this boundary runs.
    """
    configured = os.environ.get('SHIPPO_WEBHOOK_ALLOWED_IPS', '').strip()
    if not configured:
        return  # HMAC / encrypted URL token remains mandatory independently.
    try:
        allowed = [ipaddress.ip_network(value.strip()) for value in configured.split(',')]
        trusted = [ipaddress.ip_network(value.strip()) for value in
                   os.environ.get('TRACKING_WEBHOOK_TRUSTED_PROXY_CIDRS', '').split(',') if value.strip()]
        peer = ipaddress.ip_address(request.client.host)
        forwarded = request.headers.getlist('x-forwarded-for')
        if any(peer in network for network in trusted):
            if len(forwarded) != 1:
                raise ValueError('Missing or ambiguous proxy chain')
            chain = [ipaddress.ip_address(item.strip()) for item in forwarded[0].split(',')]
            if len(chain) > 16:
                raise ValueError('Proxy chain too long')
            while chain and any(peer in network for network in trusted):
                peer = chain.pop()
        if not any(peer in network for network in allowed):
            raise ValueError('Source outside allowlist')
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(403, 'Tracking source IP is not permitted') from None
