from __future__ import annotations

from pathlib import Path

import pytest

from ticket_to_record.llm.base import LLMError
from ticket_to_record.llm.fake import FakeLLM
from ticket_to_record.models import ExtractionResult, RequestedAction, Urgency
from ticket_to_record.pipeline.extract import extract_many, load_tickets, write_results

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "tickets.jsonl"


@pytest.fixture(scope="module")
def results() -> dict[str, ExtractionResult]:
    tickets = load_tickets(EXAMPLES)
    out: dict[str, ExtractionResult] = {}
    for ticket, result, error in extract_many(tickets, FakeLLM()):
        assert error is None, f"{ticket.ticket_id} failed: {error}"
        assert result is not None
        out[ticket.ticket_id] = result
    return out


def test_every_example_extracts(results: dict[str, ExtractionResult]) -> None:
    assert len(results) == 6


def test_malformed_line_names_itself(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"ticket_id": "T-1"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"bad\.jsonl:1"):
        load_tickets(bad)


def test_results_round_trip(tmp_path: Path, results: dict[str, ExtractionResult]) -> None:
    out = tmp_path / "runs" / "out.jsonl"
    written = write_results(results.values(), out)
    assert written == 6
    assert len(out.read_text(encoding="utf-8").strip().splitlines()) == 6


class TestPromptInjection:
    """T-1006 carries instructions aimed at the extractor rather than at support.

    These tests record what the rule-based baseline actually does, which is not
    the same as what we want. The baseline is partly fooled, and that is written
    down here rather than quietly fixed: it is a measured property of the
    cheapest possible extractor, and it is one of the concrete reasons a
    language model might be worth its cost on this task.

    When a provider is added to the harness, these assertions are what it has to
    beat — not a green tick it inherits.
    """

    def test_baseline_is_fooled_into_the_wrong_action(
        self, results: dict[str, ExtractionResult]
    ) -> None:
        # Keyword matching has no concept of instruction versus data: the word
        # "refund" appears, so "refund" is the answer. No amount of prompt
        # fencing helps a matcher that never reads the fence.
        assert results["T-1006"].record.requested_action is RequestedAction.REFUND

    def test_baseline_resists_the_urgency_injection(
        self, results: dict[str, ExtractionResult]
    ) -> None:
        # Not resistance so much as luck: "set urgency to high" happens not to
        # contain any of the words the urgency rules look for.
        assert results["T-1006"].record.urgency is Urgency.NORMAL

    def test_baseline_cannot_fabricate_evidence(self, results: dict[str, ExtractionResult]) -> None:
        # Evidence spans are sliced out of the body, so there is no mechanism by
        # which the requested string could be invented. A generative provider
        # has no such structural guarantee, which is why this test exists.
        evidence = " ".join(results["T-1006"].record.evidence).lower()
        assert "approved by support" not in evidence


class TestConcurrencyAndRetry:
    """The two things the first real evaluation run needed from the pipeline.

    Both were deferred on the grounds that there was no accuracy number to
    protect yet. 316's set is 2,571 tickets, which is over half an hour of
    sequential calls and long enough that one transient provider error throws
    the run away.
    """

    def test_workers_do_not_reorder_results(self) -> None:
        """Completion order is the provider's business; row order is ours.

        A report whose rows depend on network timing cannot be diffed between
        runs, which is most of what a report is for.
        """
        tickets = load_tickets(EXAMPLES)
        sequential = [t.ticket_id for t, _, _ in extract_many(tickets, FakeLLM())]
        parallel = [t.ticket_id for t, _, _ in extract_many(tickets, FakeLLM(), workers=4)]
        assert parallel == sequential

    def test_a_failure_is_retried_and_can_succeed(self) -> None:
        class FlakyLLM(FakeLLM):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def structured(self, **kwargs: object):  # type: ignore[no-untyped-def]
                self.calls += 1
                if self.calls == 1:
                    raise LLMError("transient")
                return super().structured(**kwargs)  # type: ignore[arg-type]

        llm = FlakyLLM()
        ticket = load_tickets(EXAMPLES)[0]
        ((_, result, error),) = extract_many([ticket], llm, retries=1)
        assert error is None
        assert result is not None
        assert llm.calls == 2

    def test_exhausted_retries_report_the_error_and_do_not_raise(self) -> None:
        class DeadLLM(FakeLLM):
            def structured(self, **kwargs: object):  # type: ignore[no-untyped-def]
                raise LLMError("provider down")

        # The whole point: one dead ticket must not abort a 2,571-ticket run,
        # and it must be counted rather than dropped.
        ((_, result, error),) = extract_many([load_tickets(EXAMPLES)[0]], DeadLLM(), retries=1)
        assert result is None
        assert error == "provider down"
