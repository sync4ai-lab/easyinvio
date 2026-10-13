from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field


class StrictOutput(BaseModel):
    model_config = ConfigDict(extra='forbid')


class QuoteIntent(StrictOutput):
    intent: Literal['QUOTE', 'HELP', 'UNSUPPORTED']
    weight_kg: str | None
    origin_country: str | None
    destination_country: str | None
    route_code: str | None


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
