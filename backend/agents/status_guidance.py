"""Recognize explanatory status questions without authorizing any action."""
import re

DOMAINS = re.compile(r'\b(?:order|shipment|parcel|quote|quoted|booking|booked|label|manifest|handover|tracking|delivery|wallet|payment|card|topup|refund|cancellation|claim|insurer|insurance|protection|return|store|sync|invitation|registration|email|chat|message|support|evidence|invoice)\b')
STATES = re.compile(r'\b(?:pending|failed|received|submitted|completed|resolved|expired|draft|unquoted|quoted|booked|manifested|dispatched|delivered|exception|unknown|stale|reserved|captured|released|credited|insured|declined|cancelled|unavailable|processing|review|transit|pickup|unfulfilled|imported|confirmed|sending|accepted|locked|verified|unsupported|due|running|dead|read|staged)\b')


def normalized(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()


def status_question(text: str) -> bool:
    """Questions about a state are help; explicit financial/shipment commands stay native."""
    value = normalized(text)
    if value in {'pending','failed','received','submitted','completed','resolved','unknown','stale','unquoted','draft','quote expired','label created'}:
        return True
    if value == 'manifest status' or re.fullmatch(r'\s*(?:track|tracking|return)(?:\s+(?:order|tracking|shipment|parcel|return))?\s+[A-Za-z0-9_-]{1,200}\s*', text, re.I):
        return False
    if re.fullmatch(r'\s*claim\s+[A-Za-z0-9_-]{1,200}\s+(?:lost|damaged)\s+.{10,1800}\s*', text, re.I | re.S):
        return False
    if re.match(r'^(?:book option|confirm option|top up \d|topup \d|return order|return tracking|return shipment|create a return|close manifest|claim \S+ (?:lost|damaged))\b', value):
        return False
    if re.fullmatch(r'(?:track|tracking)\s+[a-z0-9]+', value) and not STATES.search(value) and not value.endswith(' status'):
        return False
    explanatory = re.search(r'\b(?:mean|means|meaning|explain|why|stuck|unexpected|unwanted|status|statuses|says|showing|shows|resolve|understand)\b|\bwhat (?:should|do)\b', value)
    return bool((explanatory and (STATES.search(value) or DOMAINS.search(value)))
                or (DOMAINS.search(value) and STATES.search(value) and len(value.split()) <= 7))


def needs_status_context(text: str) -> bool:
    value = normalized(text)
    return bool(re.search(r'\b(?:pending|failed|received|submitted|completed|resolved)\b', value) and not DOMAINS.search(value))
