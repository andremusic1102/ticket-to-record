"""Ticket in, record out.

This was the straight-line version — one ticket, one call, in order — and the
note here said concurrency and retry were deferred until there was an accuracy
number to protect. There is one now, and getting it needed both: the first real
evaluation set is 2,571 tickets, which is over half an hour of sequential calls
and long enough that a single transient provider error throws the run away.

So `extract_many` takes `workers` and `retries`. Both default to the old
behaviour, because the defaults are what the test suite and a fresh clone run,
and neither should silently acquire a thread pool.

Still deliberately absent: cost accounting across a run, and chunking for
tickets past a context window. The seam is here — every call returns latency and
token counts, and failures are captured per ticket rather than aborting the
batch.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
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


def _attempt(
    ticket: Ticket, llm: StructuredLLM, retries: int
) -> tuple[Ticket, ExtractionResult | None, str | None]:
    """One ticket, retried on provider failure with exponential backoff.

    Jittered because the whole point of the thread pool is that requests are in
    step with each other; retrying them in step as well turns one rate-limit
    response into a synchronised second wave of them.

    A failure that survives every attempt returns its *last* error, and the run
    continues. One bad ticket must not cost a batch, and a run that silently
    drops tickets reports accuracy for the subset that happened to work — the
    most flattering and least honest number available.
    """
    last = ""
    for attempt in range(retries + 1):
        try:
            return ticket, extract_one(ticket, llm), None
        except LLMError as exc:
            last = str(exc)
            if attempt < retries:
                time.sleep((2**attempt) * (0.5 + random.random()))
    return ticket, None, last


def extract_many(
    tickets: Iterable[Ticket],
    llm: StructuredLLM,
    *,
    workers: int = 1,
    retries: int = 0,
) -> Iterator[tuple[Ticket, ExtractionResult | None, str | None]]:
    """Yield ``(ticket, result, error)`` for each ticket, in input order.

    ``workers=1`` runs exactly as before, one call at a time, and is the
    default so that nothing acquires a thread pool by accident. Above 1, calls
    overlap but results are still yielded in the order the tickets arrived:
    completion order is the provider's business, and a report whose row order
    depends on network timing is a report that cannot be diffed between runs.
    """
    if workers <= 1:
        for ticket in tickets:
            yield _attempt(ticket, llm, retries)
        return

    ordered = list(tickets)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        yield from pool.map(lambda t: _attempt(t, llm, retries), ordered)


def write_results(results: Iterable[ExtractionResult], path: Path) -> int:
    """Write results as JSON Lines. Returns the number of rows written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result.model_dump(mode="json"), ensure_ascii=False) + "\n")
            count += 1
    return count
