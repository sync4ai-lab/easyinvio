"""Deterministic CX routing. These proposals never authorize a purchase or credit."""
import re
from backend.agents.models import ConversationalIntent


def cx_intent(text: str) -> ConversationalIntent | None:
    reference = re.search(r'\b(?:order|shipment|tracking|reference)\s+([A-Za-z0-9_-]{1,200})', text, re.I)
    target = reference[1] if reference else None
    if target and target.lower() in {'is', 'has', 'was', 'refund', 'please'}:
        target = None
    if re.search(r'\b(?:refund|void)\b', text, re.I):
        action = 'REFUND_INQUIRY'
    elif re.search(r'\b(?:complaint|complain|damaged|missing|delayed|missed delivery|lost)\b', text, re.I):
        action = 'COMPLAINT'
    elif re.search(r'\b(?:service request|support|address change|change (?:my |the )?address|billing issue)\b', text, re.I):
        action = 'SERVICE_REQUEST'
    else:
        return None
    category = ('DAMAGED' if re.search(r'damag', text, re.I) else
                'MISSING_DELAYED' if re.search(r'missing|delayed|missed|lost', text, re.I) else
                'ADDRESS_CHANGE' if re.search(r'address', text, re.I) else 'BILLING_OTHER')
    return ConversationalIntent(intent=action, target_reference_id=target,
        issue_category=category, description_notes=text[:1000])
