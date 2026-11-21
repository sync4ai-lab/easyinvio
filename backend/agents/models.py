import re
from enum import StrEnum
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictOutput(BaseModel):
    model_config = ConfigDict(extra='forbid')


class QuoteIntent(StrictOutput):
    intent: Literal['QUOTE', 'HELP', 'UNSUPPORTED']
    weight_kg: str | None
    origin_country: str | None
    destination_country: str | None
    route_code: str | None


class ConversationalIntent(StrictOutput):
    """Model proposals are data; only the gateway authorizes an action."""
    intent: Literal['QUOTE', 'BOOK_RESERVATION', 'TRACK_PACKAGE', 'TOPUP_WALLET', 'FILE_CLAIM', 'TRIGGER_RETURN', 'CLOSE_MANIFEST', 'MANIFEST_STATUS', 'SERVICE_REQUEST', 'COMPLAINT', 'REFUND_INQUIRY', 'HELP']
    issue_category: Literal['DAMAGED','MISSING_DELAYED','ADDRESS_CHANGE','BILLING_OTHER'] | None = None
    weight_kg: str | None = None
    origin_country: str | None = None
    destination_country: str | None = None
    origin_postal_code: str | None = Field(default=None, min_length=1, max_length=30)
    destination_postal_code: str | None = Field(default=None, min_length=1, max_length=30)
    origin_city: str | None = Field(default=None, min_length=1, max_length=100)
    destination_city: str | None = Field(default=None, min_length=1, max_length=100)
    route_code: str | None = None
    target_reference_id: str | None = Field(default=None, max_length=200)
    monetary_amount: Decimal | None = Field(default=None, ge=1, le=10000, decimal_places=2, allow_inf_nan=False)
    selection_index: int | None = Field(default=None, ge=1, le=10, strict=True)
    description_notes: str | None = Field(default=None, max_length=2000)
    cargo_type: Literal['PARCEL','PALLET','OVERLAND_FREIGHT'] = 'PARCEL'
    dimensions_cm: list[Decimal] | None = Field(default=None,min_length=3,max_length=3)
    knowledge_kind: Literal['APP_FAQ','LOGISTICS_ADVICE'] | None = None

    @field_validator('dimensions_cm')
    @classmethod
    def dimensions_valid(cls,value):
        if value is not None and any(not x.is_finite() or x<=0 or x>1000 for x in value):raise ValueError('Use three positive dimensions up to 1000 cm')
        return value

    @field_validator('monetary_amount', mode='before')
    @classmethod
    def exact_amount(cls, value):
        if value is None:
            return value
        if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
            raise ValueError('Use an exact decimal amount, not a floating point value')
        if not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?', str(value)):
            raise ValueError('Use a positive amount with at most two decimal places')
        return Decimal(value)


class ShippingIntent(StrictOutput):
    """Shared UX taxonomy; existing execution intents remain backward compatible."""
    intent: Literal['QUOTE','BOOK_SELECTION','TRACK','CHANGE_ADDRESS','RETURN_REQUEST','REFUND_OR_CLAIM','COMPLAINT_OR_SUPPORT','KNOWLEDGE_QUERY']
    knowledge_kind: Literal['APP_FAQ','LOGISTICS_ADVICE'] | None = None
    facts: ConversationalIntent | None = None


class ColumnMapping(StrictOutput):
    source: str
    target: str


class HeaderMapping(StrictOutput):
    columns: list[ColumnMapping]
    unresolved: list[str]


class HSSelection(StrictOutput):
    hs_code: str | None
    explanation: str
    missing_attributes: list[str]


class CitedAnswer(StrictOutput):
    answer: str
    chunk_ids: list[str]
    insufficient_evidence: bool


class State(StrEnum):
    RECEIVED = 'RECEIVED'
    VALIDATING = 'VALIDATING'
    NEEDS_INPUT = 'NEEDS_INPUT'
    READY = 'READY'
    EXECUTING = 'EXECUTING'
    COMPLETED = 'COMPLETED'
    REVIEW_REQUIRED = 'REVIEW_REQUIRED'


class Workflow(StrictOutput):
    id: UUID = Field(default_factory=uuid4)
    state: State = State.RECEIVED
    transitions: list[State] = Field(default_factory=lambda: [State.RECEIVED])

    def move(self, target):
        allowed = {
            State.RECEIVED: {State.VALIDATING},
            State.VALIDATING: {State.READY, State.NEEDS_INPUT, State.REVIEW_REQUIRED},
            State.READY: {State.EXECUTING, State.COMPLETED},
            State.EXECUTING: {State.COMPLETED, State.REVIEW_REQUIRED},
            State.COMPLETED: set(), State.NEEDS_INPUT: set(), State.REVIEW_REQUIRED: set(),
        }
        if target not in allowed[self.state]:
            raise ValueError('Invalid supervisor transition')
        self.state = target
        self.transitions.append(target)


class MessageRequest(StrictOutput):
    text: str = Field(min_length=3, max_length=2000)


class HelpQuestion(StrictOutput):
    query: str = Field(min_length=3, max_length=800)
