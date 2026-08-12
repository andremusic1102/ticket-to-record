from __future__ import annotations

from datetime import datetime

import pytest

from ticket_to_record.llm.base import LLMError
from ticket_to_record.llm.fake import FakeLLM
from ticket_to_record.models import Channel, ExtractedRecord, IssueCategory, RequestedAction, Ticket
from ticket_to_record.prompts import SYSTEM, build_user_prompt


def _ask(body: str, subject: str = "Test") -> ExtractedRecord:
    ticket = Ticket(
        ticket_id="T-0000",
        channel=Channel.EMAIL,
        received_at=datetime(2026, 3, 4, 9, 0),
        subject=subject,
        body=body,
    )
    call = FakeLLM().structured(
        system=SYSTEM,
        user=build_user_prompt(ticket),
        schema=ExtractedRecord,
    )
    return call.value


class TestIdentifiers:
    def test_reads_model_and_serial(self) -> None:
        record = _ask("Model MDL-4420X, serial number SN-88213047 stopped working.")
        assert record.product_model == "MDL-4420X"
        assert record.serial_number == "SN-88213047"

    def test_absent_identifiers_are_null_not_invented(self) -> None:
        record = _ask("It makes a rattling noise and I cannot find any paperwork.")
        assert record.product_model is None
        assert record.serial_number is None

    def test_normalises_us_dates(self) -> None:
        assert _ask("Bought it 12/18/2024.").purchase_date == "2024-12-18"

    def test_prefers_iso_dates(self) -> None:
        assert _ask("Purchased 2025-11-02.").purchase_date == "2025-11-02"


class TestClassification:
    def test_missing_part_beats_other_hints(self) -> None:
        record = _ask("The manual was missing from the box.")
        assert record.issue_category is IssueCategory.MISSING_PART

    def test_refund_request(self) -> None:
        assert _ask("I want a refund.").requested_action is RequestedAction.REFUND

    def test_safety_language_raises_urgency(self) -> None:
        record = _ask("This is a safety issue and my son was riding it.")
        assert record.urgency.value == "high"

    def test_coverage_is_null_when_unstated(self) -> None:
        assert _ask("The belt snapped.").under_coverage is None


class TestContract:
    def test_deterministic(self) -> None:
        body = "Model MDL-3300 serial SN-77120993, brake pads failed. I want a refund."
        assert _ask(body) == _ask(body)

    def test_evidence_is_copied_from_the_body(self) -> None:
        body = "Model MDL-2100 arrived without the manual."
        record = _ask(body)
        assert record.evidence
        for span in record.evidence:
            assert span in " ".join(body.split())

    def test_rejects_schemas_it_cannot_produce(self) -> None:
        with pytest.raises(LLMError, match="ExtractedRecord"):
            FakeLLM().structured(system="", user="", schema=Ticket)
