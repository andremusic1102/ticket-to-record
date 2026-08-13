"""Domain models.

Two deliberate choices here, both of which the evaluation harness depends on:

1. **The extraction target is small.** A wide schema makes an accuracy number
   meaningless — the model scores well on the easy fields and the hard ones
   disappear into the average. Every field below is one a human would otherwise
   have to read the ticket and type by hand.

2. **The model must cite itself.** ``evidence`` holds verbatim spans copied from
   the ticket body. A field with no supporting span is a candidate hallucination,
   which means hallucination becomes measurable without a second judge model.

Note that dates crossing the model boundary are typed ``str``, not ``date``.
Structured-output APIs vary in how they handle JSON Schema ``format`` keywords,
and a rejected request is a worse failure than a string that needs parsing.
Normalisation happens on our side, in :func:`parse_iso_date`.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, Field

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Channel(StrEnum):
    """How the ticket reached the queue."""

    EMAIL = "email"
    PHONE = "phone"
    WEB_FORM = "web_form"
    CHAT = "chat"


class IssueCategory(StrEnum):
    """Coarse bucket for the reported problem."""

    MECHANICAL = "mechanical"
    ELECTRICAL = "electrical"
    COSMETIC = "cosmetic"
    MISSING_PART = "missing_part"
    DOCUMENTATION = "documentation"
    OTHER = "other"


class RequestedAction(StrEnum):
    """What the customer is asking for, not what they will get."""

    REPAIR = "repair"
    REPLACEMENT = "replacement"
    REFUND = "refund"
    PARTS_ONLY = "parts_only"
    INFORMATION = "information"


class Urgency(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class Ticket(BaseModel):
    """A single inbound support request, as received."""

    ticket_id: str
    channel: Channel
    received_at: datetime
    subject: str
    body: str


class ExtractedRecord(BaseModel):
    """The structured record an operator would otherwise key in by hand.

    Every field is required so the model cannot silently omit one; fields that
    may genuinely be absent from the ticket are nullable instead. "Absent" and
    "not attempted" are different failures and the harness scores them
    differently.
    """

    product_model: str | None = Field(
        description="Model designation exactly as written in the ticket, or null if absent."
    )
    serial_number: str | None = Field(
        description="Serial or unit identifier exactly as written, or null if absent."
    )
    purchase_date: str | None = Field(
        description="Purchase date as YYYY-MM-DD, or null if the ticket does not state one."
    )
    issue_category: IssueCategory
    symptom: str = Field(
        description="One sentence, in the customer's own terms, describing what is wrong."
    )
    requested_action: RequestedAction
    urgency: Urgency
    parts_mentioned: list[str] = Field(
        description="Component names named in the ticket. Empty list if none."
    )
    under_coverage: bool | None = Field(
        description=(
            "True or false only if the ticket states the coverage status. "
            "Null if it is not stated — do not infer it from the purchase date."
        )
    )
    evidence: list[str] = Field(
        description=(
            "Verbatim spans copied from the ticket body that support the fields above. "
            "Copy exactly; do not paraphrase."
        )
    )


class ExtractionResult(BaseModel):
    """An extraction plus everything needed to evaluate and cost it.

    Kept separate from :class:`ExtractedRecord` because this half is never sent
    to the model — mixing them would put our own telemetry into the prompt.
    """

    ticket_id: str
    record: ExtractedRecord
    provider: str
    model: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None

    # Only fields whose contract is "copy this character for character" can be
    # span-checked. Enums and booleans are labels rather than quotations, and
    # `purchase_date` is explicitly normalised to ISO form — a ticket saying
    # "12/18/2024" yields "2024-12-18", which will never appear in the evidence.
    # Checking it anyway would manufacture hallucinations that did not happen,
    # and a metric that inflates itself is worse than no metric.
    VERBATIM_FIELDS: ClassVar[tuple[str, ...]] = ("product_model", "serial_number")

    @property
    def unsupported_fields(self) -> list[str]:
        """Copied fields whose value appears in no evidence span.

        A cheap, judge-free hallucination signal.
        """
        joined = " ".join(self.record.evidence).lower()
        return [
            name
            for name in self.VERBATIM_FIELDS
            if (value := getattr(self.record, name)) and str(value).lower() not in joined
        ]


class LabelledTicket(BaseModel):
    """A ticket paired with the record it should produce.

    The evaluation set and the synthetic generator both speak this shape, so a
    hand-labelled ticket and a generated one are interchangeable to the harness.
    That matters more than it looks: the point of generating data is to develop
    against it and then swap in real labels without touching the scorer.

    ``notes`` records why a ticket exists — "purchase date absent", "injection
    attempt". A failure report that can group by intent is worth more than one
    that lists ticket ids.

    ``scored_fields`` exists because real evaluation sets are ragged. One field
    may be labelled on thousands of tickets — a serial that appears both in the
    text and in a structured column can be checked automatically — while the
    rest are labelled on the fifty somebody read by hand. Forcing one
    denominator onto all of them would either throw away the cheap labels or
    publish a single blended accuracy that hides a 70-fold difference in
    sample size. ``None`` means every field is labelled — the synthetic case.
    """

    ticket: Ticket
    gold: ExtractedRecord
    notes: list[str] = Field(default_factory=list)
    scored_fields: list[str] | None = None

    def scores(self, field: str) -> bool:
        """Whether this ticket carries a usable label for ``field``."""
        return self.scored_fields is None or field in self.scored_fields


def parse_iso_date(value: str | None) -> date | None:
    """Return ``value`` as a date, or None if it is missing or malformed.

    Malformed is treated as missing on purpose: a wrong date that parses is far
    more damaging downstream than an absent one, and the harness already counts
    how often the field comes back unusable.
    """
    if value is None or not _ISO_DATE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
