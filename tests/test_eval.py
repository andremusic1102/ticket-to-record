"""Tests for the scorer.

The scorer is the part of this repository that can quietly lie. A pipeline bug
shows up as an exception; a scoring bug shows up as a number that looks fine.
So these tests are mostly about the ways an accuracy figure can flatter:
counting failed calls as successes, ignoring per-field denominators, or giving
credit to a strategy that never reads the ticket.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ticket_to_record.eval.score import Kind, score_run
from ticket_to_record.models import (
    Channel,
    ExtractedRecord,
    ExtractionResult,
    IssueCategory,
    LabelledTicket,
    RequestedAction,
    Ticket,
    Urgency,
)

SERIAL = "77213047-K"


def _record(**overrides: object) -> ExtractedRecord:
    base: dict[str, object] = {
        "product_model": "MDL-1234X",
        "serial_number": SERIAL,
        "purchase_date": "2025-03-04",
        "issue_category": IssueCategory.ELECTRICAL,
        "symptom": "will not hold a charge overnight",
        "requested_action": RequestedAction.REPAIR,
        "urgency": Urgency.NORMAL,
        "parts_mentioned": ["battery"],
        "under_coverage": True,
        "evidence": [f"Serial number {SERIAL}."],
    }
    base.update(overrides)
    return ExtractedRecord.model_validate(base)


def _labelled(ticket_id: str, gold: ExtractedRecord, **kwargs: object) -> LabelledTicket:
    return LabelledTicket(
        ticket=Ticket(
            ticket_id=ticket_id,
            channel=Channel.EMAIL,
            received_at=datetime(2026, 2, 1, tzinfo=UTC),
            subject="Battery problem",
            body=f"Serial number {SERIAL}. It will not hold a charge overnight.",
        ),
        gold=gold,
        **kwargs,  # type: ignore[arg-type]
    )


def _result(ticket_id: str, record: ExtractedRecord) -> ExtractionResult:
    return ExtractionResult(
        ticket_id=ticket_id,
        record=record,
        provider="test",
        model="test",
        latency_ms=1,
    )


class TestPerfectAndEmpty:
    def test_identical_records_score_one(self) -> None:
        gold = _record()
        report = score_run([_labelled("T1", gold)], {"T1": _result("T1", gold)})
        for name, entry in report.fields.items():
            assert entry.score == 1.0, name

    def test_failed_calls_are_counted_not_scored(self) -> None:
        # Scoring a call that never happened as "wrong" blames the model for an
        # outage; dropping it silently reports accuracy for the subset that
        # worked. Neither is acceptable, so it is counted separately.
        gold = _record()
        report = score_run([_labelled("T1", gold)], {}, failures=1)
        assert report.tickets == 1
        assert report.extracted == 0
        assert report.failed == 1
        assert report.fields["serial_number"].n == 0


class TestFailureModes:
    def test_fabricated_when_gold_is_null(self) -> None:
        report = score_run(
            [_labelled("T1", _record(purchase_date=None))],
            {"T1": _result("T1", _record(purchase_date="2025-03-04"))},
        )
        entry = report.fields["purchase_date"]
        assert (entry.fabricated, entry.missed, entry.wrong_value) == (1, 0, 0)

    def test_missed_when_model_abstains(self) -> None:
        report = score_run(
            [_labelled("T1", _record())],
            {"T1": _result("T1", _record(purchase_date=None))},
        )
        entry = report.fields["purchase_date"]
        assert (entry.fabricated, entry.missed, entry.wrong_value) == (0, 1, 0)

    def test_wrong_value_when_both_present(self) -> None:
        report = score_run(
            [_labelled("T1", _record())],
            {"T1": _result("T1", _record(purchase_date="2024-01-01"))},
        )
        entry = report.fields["purchase_date"]
        assert (entry.fabricated, entry.missed, entry.wrong_value) == (0, 0, 1)

    def test_date_is_compared_after_normalisation(self) -> None:
        # A malformed date is treated as absent, so this is a miss rather than
        # a wrong value — the same rule parse_iso_date already applies.
        report = score_run(
            [_labelled("T1", _record())],
            {"T1": _result("T1", _record(purchase_date="4 March 2025"))},
        )
        assert report.fields["purchase_date"].missed == 1


class TestBaseline:
    def test_always_null_scores_exactly_the_baseline(self) -> None:
        """The whole reason the baseline column exists.

        Nine of ten tickets have no purchase date. A strategy that never reads
        the ticket and always answers null gets 90%, and without the baseline
        column that would read as a strong result.
        """
        labelled = [
            _labelled(f"T{i}", _record(purchase_date=None if i else "2025-03-04"))
            for i in range(10)
        ]
        results = {
            item.ticket.ticket_id: _result(item.ticket.ticket_id, _record(purchase_date=None))
            for item in labelled
        }
        entry = score_run(labelled, results).fields["purchase_date"]
        assert entry.score == 0.9
        assert entry.baseline == 0.9
        assert entry.lift == 0.0

    def test_soft_fields_report_no_baseline(self) -> None:
        report = score_run([_labelled("T1", _record())], {"T1": _result("T1", _record())})
        assert report.fields["symptom"].kind is Kind.TEXT
        assert report.fields["symptom"].soft
        assert report.fields["symptom"].baseline == 0.0


class TestRaggedLabels:
    def test_each_field_carries_its_own_denominator(self) -> None:
        """A field labelled on more tickets must report the larger n.

        This is the shape a real evaluation set has: one field checkable
        automatically against a structured column across thousands of tickets,
        the rest labelled by hand on a few dozen. One blended denominator would
        hide the difference.
        """
        labelled = [
            _labelled("T1", _record()),  # fully labelled
            _labelled("T2", _record(), scored_fields=["serial_number"]),
            _labelled("T3", _record(), scored_fields=["serial_number"]),
        ]
        results = {
            item.ticket.ticket_id: _result(item.ticket.ticket_id, _record()) for item in labelled
        }
        report = score_run(labelled, results)
        assert report.fields["serial_number"].n == 3
        assert report.fields["purchase_date"].n == 1

    def test_baseline_uses_only_scored_rows(self) -> None:
        # Borrowing the majority class from rows a field was not scored on
        # would make the comparison unfair in whichever direction happened to
        # be convenient.
        labelled = [
            _labelled("T1", _record(under_coverage=True)),
            _labelled("T2", _record(under_coverage=False), scored_fields=["serial_number"]),
        ]
        results = {
            item.ticket.ticket_id: _result(item.ticket.ticket_id, _record()) for item in labelled
        }
        entry = score_run(labelled, results).fields["under_coverage"]
        assert entry.n == 1
        assert entry.baseline == 1.0


class TestSoftScoring:
    def test_set_f1_gives_partial_credit(self) -> None:
        report = score_run(
            [_labelled("T1", _record(parts_mentioned=["battery", "charger"]))],
            {"T1": _result("T1", _record(parts_mentioned=["battery"]))},
        )
        # 2 * 1 shared / (2 gold + 1 predicted)
        assert abs(report.fields["parts_mentioned"].score - 2 / 3) < 1e-9

    def test_empty_sets_agree(self) -> None:
        report = score_run(
            [_labelled("T1", _record(parts_mentioned=[]))],
            {"T1": _result("T1", _record(parts_mentioned=[]))},
        )
        assert report.fields["parts_mentioned"].score == 1.0

    def test_paraphrase_earns_partial_credit(self) -> None:
        report = score_run(
            [_labelled("T1", _record(symptom="will not hold a charge overnight"))],
            {"T1": _result("T1", _record(symptom="does not hold a charge overnight"))},
        )
        assert 0.5 < report.fields["symptom"].score < 1.0


class TestHallucination:
    def test_unsupported_verbatim_field_is_flagged(self) -> None:
        report = score_run(
            [_labelled("T1", _record())],
            {"T1": _result("T1", _record(serial_number="Z999", evidence=["nothing useful"]))},
        )
        assert report.hallucinated == 1
        assert report.hallucination_rate == 1.0
