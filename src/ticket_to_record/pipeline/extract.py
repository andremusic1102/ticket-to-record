"""Ticket in, record out.

Scope note: this is the straight-line version — one ticket, one call, in order.
Concurrency, retry with backoff, cost accounting across a run, and chunking for
tickets that exceed a context window are deliberately not here yet. Adding them
before there is an accuracy number to protect would be optimising a pipeline
nobody has measured.

What *is* here is the seam they will attach to: every call already returns
latency and token counts, and failures are captured per ticket instead of
aborting the batch.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from ticket_to_record.llm.base import LLMError, StructuredLLM
from ticket_to_record.models import ExtractedRecord, ExtractionResult, Ticket
from ticket_to_record.prompts import SYSTEM, build_user_prompt


def load_tickets(path: Path) -> list[Ticket]:
    """Read tickets from a JSON Lines file.

    JSONL rather than a single JSON array so a run can stream and a malformed
    line names itself instead of invalidating the whole file.
    """
    tickets: list[Ticket] = []
    with path.open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                tickets.append(Ticket.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(f"{path}:{lineno} is not a valid ticket: {exc}") from exc
    return tickets


def extract_one(ticket: Ticket, llm: StructuredLLM) -> ExtractionResult:
    """Extract a single ticket. Raises :class:`LLMError` on provider failure."""
    call = llm.structured(
        system=SYSTEM,
        user=build_user_prompt(ticket),
        schema=ExtractedRecord,
    )
    return ExtractionResult(
        ticket_id=ticket.ticket_id,
        record=call.value,
        provider=llm.name,
        model=llm.model,
        latency_ms=call.latency_ms,
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
    )


def extract_many(
    tickets: Iterable[Ticket],
    llm: StructuredLLM,
) -> Iterator[tuple[Ticket, ExtractionResult | None, str | None]]:
    """Yield ``(ticket, result, error)`` for each ticket, in order.

    One bad ticket must not cost a whole batch. The error is returned rather
    than raised so the caller can count failures — a run that silently drops
    tickets reports an accuracy figure for the subset that happened to work,
    which is the most flattering and least honest number available.
    """
    for ticket in tickets:
        try:
            yield ticket, extract_one(ticket, llm), None
        except LLMError as exc:
            yield ticket, None, str(exc)


def write_results(results: Iterable[ExtractionResult], path: Path) -> int:
    """Write results as JSON Lines. Returns the number of rows written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result.model_dump(mode="json"), ensure_ascii=False) + "\n")
            count += 1
    return count
