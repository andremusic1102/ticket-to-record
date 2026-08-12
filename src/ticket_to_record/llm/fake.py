"""A deterministic provider that never makes a network call.

This is not a mock in the testing sense — it is a real, if crude, extractor
built from regular expressions and keyword lists. That matters for three
reasons:

* The whole pipeline, CLI and test suite run with no key and no spend, so CI can
  exercise the real code path rather than a stubbed-out one.
* It is the **baseline the language model has to beat**. "The model gets 84%" is
  not a result on its own; "the model gets 84% where regular expressions get
  61%" is. Without a baseline there is no way to tell whether the model is
  earning its cost.
* It is deterministic, so a failing test means the pipeline changed, not that
  the weather in the sampler changed.
"""

from __future__ import annotations

import re
import time
from typing import cast

from pydantic import BaseModel

from ticket_to_record.llm.base import LLMCall, LLMError
from ticket_to_record.models import (
    ExtractedRecord,
    IssueCategory,
    RequestedAction,
    Urgency,
)

_BODY = re.compile(r"<<<TICKET_BODY\n(.*)\nTICKET_BODY", re.S)

# The captured token must contain a digit. Without that, "my unit failed"
# yields a product model of "failed" — and an artificially weak baseline
# flatters whatever it is being compared against, which defeats the point of
# having one.
_MODEL = re.compile(
    r"\b(?:model|unit)\s*(?:number|no\.?|#)?\s*[:#-]?\s*([A-Z][A-Z0-9-]*\d[A-Z0-9-]*)", re.I
)
_SERIAL = re.compile(r"\b(?:serial(?:\s*number)?|s/n|sn)\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{4,})", re.I)
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_US_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")

_CATEGORY_HINTS: tuple[tuple[IssueCategory, tuple[str, ...]], ...] = (
    (IssueCategory.MISSING_PART, ("missing", "not included", "never arrived", "left out")),
    (IssueCategory.ELECTRICAL, ("battery", "charger", "wiring", "fuse", "short", "won't power")),
    (IssueCategory.MECHANICAL, ("leak", "grinding", "seized", "vibration", "belt", "bearing")),
    (IssueCategory.COSMETIC, ("scratch", "dent", "chipped", "paint", "scuff")),
    (IssueCategory.DOCUMENTATION, ("manual", "instructions", "paperwork", "invoice", "receipt")),
)

_ACTION_HINTS: tuple[tuple[RequestedAction, tuple[str, ...]], ...] = (
    (RequestedAction.REFUND, ("refund", "money back", "return it")),
    (RequestedAction.REPLACEMENT, ("replace", "replacement", "new one", "swap")),
    (RequestedAction.PARTS_ONLY, ("send the part", "ship me the", "just the part", "spare")),
    (RequestedAction.REPAIR, ("repair", "fix", "service it")),
)

_HIGH_URGENCY = ("urgent", "asap", "immediately", "safety", "injur", "unsafe", "dangerous")
_LOW_URGENCY = ("no rush", "whenever", "not urgent", "no hurry")

_PARTS = (
    "battery",
    "charger",
    "wiring harness",
    "throttle",
    "brake pad",
    "seat",
    "fender",
    "bearing",
    "belt",
    "fuse",
    "switch",
    "display",
    "motor",
    "pump",
    "filter",
    "bolt",
    "bracket",
    "cable",
    "gasket",
    "valve",
)


class FakeLLM:
    """Rule-based extraction. Satisfies :class:`~ticket_to_record.llm.base.StructuredLLM`."""

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "rules-v1"

    def structured[T: BaseModel](self, *, system: str, user: str, schema: type[T]) -> LLMCall[T]:
        if schema is not ExtractedRecord:
            raise LLMError(
                f"{self.name} only knows how to produce ExtractedRecord, not {schema.__name__}. "
                "Extend the rules or use a real provider."
            )
        started = time.perf_counter()
        record = _extract(_body_of(user))
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return LLMCall(
            value=cast(T, record),
            raw_text=record.model_dump_json(),
            latency_ms=elapsed_ms,
        )


def _body_of(user_prompt: str) -> str:
    """Pull the ticket body back out of the rendered prompt.

    The fake reads the same prompt a real provider would, rather than being
    handed the ticket object directly. That keeps the two on genuinely the same
    code path — a prompt-rendering bug breaks both, instead of hiding behind the
    fake and only surfacing on a paid call.
    """
    match = _BODY.search(user_prompt)
    return match.group(1) if match else user_prompt


def _first(pattern: re.Pattern[str], text: str) -> tuple[str | None, str | None]:
    """Return (captured value, full matched span) for the first match."""
    match = pattern.search(text)
    if match is None:
        return None, None
    return match.group(1), match.group(0)


def _extract(body: str) -> ExtractedRecord:
    lowered = body.lower()
    evidence: list[str] = []

    product_model, span = _first(_MODEL, body)
    if span:
        evidence.append(span)

    serial_number, span = _first(_SERIAL, body)
    if span:
        evidence.append(span)

    purchase_date, span = _find_date(body)
    if span:
        evidence.append(span)

    category = IssueCategory.OTHER
    for candidate, hints in _CATEGORY_HINTS:
        hit = next((h for h in hints if h in lowered), None)
        if hit is not None:
            category = candidate
            evidence.append(_sentence_around(body, hit))
            break

    action = RequestedAction.INFORMATION
    for action_candidate, action_hints in _ACTION_HINTS:
        hit = next((h for h in action_hints if h in lowered), None)
        if hit is not None:
            action = action_candidate
            evidence.append(_sentence_around(body, hit))
            break

    urgency = Urgency.NORMAL
    if any(word in lowered for word in _HIGH_URGENCY):
        urgency = Urgency.HIGH
    elif any(word in lowered for word in _LOW_URGENCY):
        urgency = Urgency.LOW

    under_coverage: bool | None = None
    if "still under" in lowered or "still covered" in lowered:
        under_coverage = True
    elif "expired" in lowered or "out of coverage" in lowered:
        under_coverage = False

    return ExtractedRecord(
        product_model=product_model,
        serial_number=serial_number,
        purchase_date=purchase_date,
        issue_category=category,
        symptom=_first_sentence(body),
        requested_action=action,
        urgency=urgency,
        parts_mentioned=[part for part in _PARTS if part in lowered],
        under_coverage=under_coverage,
        evidence=[span for span in dict.fromkeys(evidence) if span],
    )


def _find_date(body: str) -> tuple[str | None, str | None]:
    iso = _ISO_DATE.search(body)
    if iso:
        return iso.group(1), iso.group(0)
    us = _US_DATE.search(body)
    if us:
        month, day, year = us.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}", us.group(0)
    return None, None


def _first_sentence(body: str) -> str:
    stripped = " ".join(body.split())
    parts = re.split(r"(?<=[.!?])\s+", stripped)
    return parts[0] if parts and parts[0] else stripped[:200]


def _sentence_around(body: str, needle: str) -> str:
    """Return the sentence containing ``needle``, as the evidence span."""
    stripped = " ".join(body.split())
    for sentence in re.split(r"(?<=[.!?])\s+", stripped):
        if needle in sentence.lower():
            return sentence
    return needle
