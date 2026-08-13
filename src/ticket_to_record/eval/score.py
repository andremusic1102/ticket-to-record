"""Score an extraction run against labelled tickets.

An accuracy number on its own is not a result. Three things have to travel with
it or it misleads, and all three are built in here rather than left to whoever
reads the output.

**A baseline.** Most of these fields have a majority answer that requires no
intelligence at all. Most tickets do not state a purchase date, so "always
answer null" scores extremely well on that field. Reporting 94% without saying
that the dumbest possible strategy gets 91% is the single easiest way to
overstate a system, so every field is reported next to the best constant
answer for that field, and the lift between them is the actual finding.

**A denominator, per field.** Evaluation sets are ragged. A field checkable
against a structured column can be labelled on thousands of tickets; the rest
are labelled on the fifty a human read. One blended number hides that, so each
field carries its own ``n`` and nothing is averaged across fields.

**The shape of the mistake.** For a field that may legitimately be absent,
"wrong" covers three different failures with different costs: the model
invented a value that was not there, missed one that was, or found the right
kind of thing and got it wrong. Downstream those are a data-integrity problem,
a coverage problem and a quality problem respectively. Collapsing them into one
percentage throws away the part an engineer would act on.

Two fields are scored softly and are labelled as such in the output. ``symptom``
is free prose, where exact match would report near-zero for answers a human
would accept, so it is scored by token overlap. ``parts_mentioned`` is a set,
scored by F1 rather than exact equality.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import StrEnum

from ticket_to_record.models import (
    ExtractedRecord,
    ExtractionResult,
    LabelledTicket,
    parse_iso_date,
)

_WORD = re.compile(r"[a-z0-9]+")


class Kind(StrEnum):
    """How a field is compared. Determines both scoring and baseline."""

    EXACT = "exact"  # nullable string, character-for-character
    DATE = "date"  # nullable, normalised before comparison
    LABEL = "label"  # closed vocabulary, never null
    FLAG = "flag"  # nullable boolean
    SET = "set"  # unordered list, F1
    TEXT = "text"  # free prose, token overlap


FIELDS: dict[str, Kind] = {
    "product_model": Kind.EXACT,
    "serial_number": Kind.EXACT,
    "purchase_date": Kind.DATE,
    "issue_category": Kind.LABEL,
    "requested_action": Kind.LABEL,
    "urgency": Kind.LABEL,
    "under_coverage": Kind.FLAG,
    "parts_mentioned": Kind.SET,
    "symptom": Kind.TEXT,
}

NULLABLE = (Kind.EXACT, Kind.DATE, Kind.FLAG)


def _tokens(value: str) -> Counter[str]:
    return Counter(_WORD.findall(value.lower()))


def _overlap_f1(gold: str, pred: str) -> float:
    """Token-level F1. Rewards saying the same thing in different words."""
    g, p = _tokens(gold), _tokens(pred)
    shared = sum((g & p).values())
    if not shared:
        return 0.0
    precision = shared / sum(p.values())
    recall = shared / sum(g.values())
    return 2 * precision * recall / (precision + recall)


def _set_f1(gold: list[str], pred: list[str]) -> float:
    g = {item.strip().lower() for item in gold}
    p = {item.strip().lower() for item in pred}
    if not g and not p:
        return 1.0
    shared = len(g & p)
    if not shared:
        return 0.0
    return 2 * shared / (len(g) + len(p))


def _normalise(kind: Kind, value: object) -> object:
    if value is None:
        return None
    if kind is Kind.DATE:
        return parse_iso_date(str(value))
    if kind is Kind.EXACT:
        return str(value).strip().lower()
    if kind is Kind.LABEL:
        return str(value)
    return value


@dataclass
class FieldScore:
    """One field's result, with everything needed to read it honestly."""

    name: str
    kind: Kind
    n: int = 0
    hits: float = 0.0
    #: Gold values, kept so the best constant answer can be computed from the
    #: same rows the model was scored on rather than from the whole set.
    gold_values: list[object] = dataclass_field(default_factory=list)
    fabricated: int = 0  # gold null, model asserted
    missed: int = 0  # gold had a value, model said null
    wrong_value: int = 0  # both present, disagree

    @property
    def score(self) -> float:
        return self.hits / self.n if self.n else 0.0

    @property
    def baseline(self) -> float:
        """Accuracy of always answering the most common gold value.

        Computed on the scored rows, so it is a fair comparison and not a
        statistic borrowed from a different sample.
        """
        if not self.gold_values:
            return 0.0
        if self.kind in (Kind.SET, Kind.TEXT):
            # No sensible constant answer exists for prose or an open set;
            # reporting one would invent a comparison.
            return 0.0
        counts = Counter(value if value is not None else "\0null" for value in self.gold_values)
        return counts.most_common(1)[0][1] / len(self.gold_values)

    @property
    def lift(self) -> float:
        return self.score - self.baseline

    @property
    def soft(self) -> bool:
        return self.kind in (Kind.SET, Kind.TEXT)


@dataclass
class Report:
    """A whole run: per-field scores plus the run-level counts."""

    fields: dict[str, FieldScore]
    tickets: int = 0
    extracted: int = 0
    failed: int = 0
    hallucinated: int = 0  # results with at least one unsupported verbatim field
    provider: str = ""
    model: str = ""

    @property
    def hallucination_rate(self) -> float:
        return self.hallucinated / self.extracted if self.extracted else 0.0


def _compare(kind: Kind, gold: object, pred: object) -> tuple[float, str | None]:
    """Return ``(credit, failure_mode)``.

    ``failure_mode`` is one of fabricated / missed / wrong_value, or None when
    the answer was right. Only nullable kinds can fabricate or miss.
    """
    if kind is Kind.SET:
        gold_list = list(gold) if isinstance(gold, list) else []
        pred_list = list(pred) if isinstance(pred, list) else []
        credit = _set_f1(gold_list, pred_list)
        return credit, None if credit == 1.0 else "wrong_value"

    if kind is Kind.TEXT:
        credit = _overlap_f1(str(gold or ""), str(pred or ""))
        return credit, None if credit >= 0.999 else "wrong_value"

    g, p = _normalise(kind, gold), _normalise(kind, pred)
    if g == p:
        return 1.0, None
    if kind in NULLABLE:
        if g is None:
            return 0.0, "fabricated"
        if p is None:
            return 0.0, "missed"
    return 0.0, "wrong_value"


def score_run(
    labelled: list[LabelledTicket],
    results: dict[str, ExtractionResult],
    *,
    failures: int = 0,
    provider: str = "",
    model: str = "",
) -> Report:
    """Score ``results`` (keyed by ticket id) against ``labelled``.

    Tickets the provider failed on are counted but not scored. That is
    deliberate and it is the honest direction: scoring them as wrong would
    conflate "the model was mistaken" with "the call did not happen", and
    silently dropping them would report accuracy for the subset that happened
    to succeed — the most flattering number available.
    """
    report = Report(
        fields={name: FieldScore(name=name, kind=kind) for name, kind in FIELDS.items()},
        tickets=len(labelled),
        failed=failures,
        provider=provider,
        model=model,
    )

    for item in labelled:
        result = results.get(item.ticket.ticket_id)
        if result is None:
            continue
        report.extracted += 1
        if result.unsupported_fields:
            report.hallucinated += 1

        for name, kind in FIELDS.items():
            if not item.scores(name):
                continue
            entry = report.fields[name]
            gold = getattr(item.gold, name)
            pred = getattr(result.record, name)
            credit, mode = _compare(kind, gold, pred)
            entry.n += 1
            entry.hits += credit
            soft = kind in (Kind.SET, Kind.TEXT)
            entry.gold_values.append(gold if soft else _normalise(kind, gold))
            if mode == "fabricated":
                entry.fabricated += 1
            elif mode == "missed":
                entry.missed += 1
            elif mode == "wrong_value":
                entry.wrong_value += 1

    return report


def gold_as_record(item: LabelledTicket) -> ExtractedRecord:
    """The gold record, for callers that want to diff it directly."""
    return item.gold
