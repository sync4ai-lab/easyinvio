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
    intent: Literal['QUOTE', 'BOOK_RESERVATION', 'TRACK_PACKAGE', 'TOPUP_WALLET', 'FILE_CLAIM', 'TRIGGER_RETURN', 'CLOSE_MANIFEST', 'MANIFEST_STATUS', 'HELP']
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
