from __future__ import annotations

from datetime import date

from ticket_to_record.models import (
    ExtractedRecord,
    ExtractionResult,
    IssueCategory,
    RequestedAction,
    Urgency,
    parse_iso_date,
)


def _record(**overrides: object) -> ExtractedRecord:
    base: dict[str, object] = {
        "product_model": "MDL-4420X",
        "serial_number": "SN-88213047",
        "purchase_date": "2025-11-02",
        "issue_category": IssueCategory.ELECTRICAL,
        "symptom": "The charger stopped working.",
        "requested_action": RequestedAction.PARTS_ONLY,
        "urgency": Urgency.NORMAL,
        "parts_mentioned": ["charger"],
        "under_coverage": True,
        "evidence": ["unit MDL-4420X", "Serial number SN-88213047", "purchased 2025-11-02"],
    }
    base.update(overrides)
    return ExtractedRecord.model_validate(base)


def _result(record: ExtractedRecord) -> ExtractionResult:
    return ExtractionResult(
        ticket_id="T-1001",
        record=record,
        provider="fake",
        model="rules-v1",
        latency_ms=1,
    )


class TestParseIsoDate:
    def test_parses_iso(self) -> None:
        assert parse_iso_date("2025-11-02") == date(2025, 11, 2)

    def test_none_passes_through(self) -> None:
        assert parse_iso_date(None) is None

    def test_wrong_shape_is_treated_as_missing(self) -> None:
        # A wrong date that parses is worse downstream than an absent one.
        assert parse_iso_date("11/02/2025") is None

    def test_impossible_date_is_treated_as_missing(self) -> None:
        assert parse_iso_date("2025-02-31") is None


class TestUnsupportedFields:
    def test_quoted_values_are_supported(self) -> None:
        assert _result(_record()).unsupported_fields == []

    def test_value_absent_from_evidence_is_flagged(self) -> None:
        record = _record(serial_number="SN-00000000")
        assert _result(record).unsupported_fields == ["serial_number"]

    def test_nulls_are_not_flagged(self) -> None:
        # A missing value is a correct answer, not a hallucination.
        record = _record(product_model=None, serial_number=None, purchase_date=None)
        assert _result(record).unsupported_fields == []
