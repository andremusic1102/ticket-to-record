"""Tests for the synthetic generator.

These assert the properties the evaluation depends on, not the prose. What the
tickets say is allowed to change; what must not change is that they stay
reproducible, that the gold labels agree with the text, and that the awkward
cases keep appearing.
"""

from __future__ import annotations

import pytest

from ticket_to_record.models import LabelledTicket
from ticket_to_record.synth.generate import ASSUMED, MEASURED, generate


class TestReproducibility:
    def test_same_seed_gives_identical_output(self) -> None:
        assert generate(40, seed=7) == generate(40, seed=7)

    def test_different_seeds_diverge(self) -> None:
        # Not a style point: an evaluation set that silently repeats would make
        # a larger --count look like more evidence than it is.
        assert generate(40, seed=7) != generate(40, seed=8)


class TestGoldAgreesWithText:
    """The label must be findable in the ticket, or the target is impossible."""

    @pytest.fixture(scope="class")
    @staticmethod
    def items() -> list[LabelledTicket]:
        return generate(300, seed=1)

    def test_serial_appears_verbatim(self, items: list[LabelledTicket]) -> None:
        for item in items:
            if item.gold.serial_number:
                assert item.gold.serial_number in item.ticket.body

    def test_model_appears_verbatim(self, items: list[LabelledTicket]) -> None:
        for item in items:
            if item.gold.product_model:
                assert item.gold.product_model in item.ticket.body

    def test_parts_appear_verbatim(self, items: list[LabelledTicket]) -> None:
        for item in items:
            for part in item.gold.parts_mentioned:
                assert part in item.ticket.body

    def test_evidence_spans_are_quotations(self, items: list[LabelledTicket]) -> None:
        # The gold record has to satisfy the same contract the model is held to.
        # If it cannot, the contract is unevaluable and the harness is scoring
        # against something no answer could achieve.
        for item in items:
            for span in item.gold.evidence:
                assert span in item.ticket.body

    def test_purchase_date_is_iso_even_when_written_otherwise(
        self, items: list[LabelledTicket]
    ) -> None:
        for item in items:
            if item.gold.purchase_date:
                assert len(item.gold.purchase_date) == 10
                assert item.gold.purchase_date[4] == "-"


class TestDistributions:
    """The awkward cases have to keep showing up, or the set gets easy."""

    @pytest.fixture(scope="class")
    @staticmethod
    def items() -> list[LabelledTicket]:
        return generate(600, seed=3)

    def test_absent_purchase_date_is_common(self, items: list[LabelledTicket]) -> None:
        absent = sum(1 for item in items if item.gold.purchase_date is None)
        expected = 1 - ASSUMED["purchase_date_stated"]
        assert abs(absent / len(items) - expected) < 0.08

    def test_serial_is_almost_always_present(self, items: list[LabelledTicket]) -> None:
        present = sum(1 for item in items if item.gold.serial_number)
        assert present / len(items) > MEASURED["serial_present"] - 0.02

    def test_injection_attempts_exist(self, items: list[LabelledTicket]) -> None:
        # A rate this low needs a large sample to show up at all, which is why
        # this fixture generates 600 rather than reusing a smaller one.
        assert any("injection attempt" in item.notes for item in items)

    def test_no_raw_contact_details(self, items: list[LabelledTicket]) -> None:
        # Bodies mimic redacted text. A literal address here would be both
        # unrealistic and a red-line scan failure waiting to happen.
        for item in items:
            assert "@" not in item.ticket.body

    def test_serial_prefixes_vary(self, items: list[LabelledTicket]) -> None:
        # Regression guard on a real defect: when every serial began "SN-", the
        # baseline's own label pattern consumed the prefix and the reported
        # serial accuracy was an artefact of the generator.
        prefixes = {item.gold.serial_number[:2] for item in items if item.gold.serial_number}
        assert len(prefixes) > 5

    def test_serials_are_not_always_labelled(self, items: list[LabelledTicket]) -> None:
        unlabelled = sum(
            1
            for item in items
            if item.gold.serial_number
            and "serial" not in item.ticket.body.lower()
            and "vin" not in item.ticket.body.lower()
        )
        assert unlabelled > 0
