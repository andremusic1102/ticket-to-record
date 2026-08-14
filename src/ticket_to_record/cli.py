"""Command line entry point."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Annotated, cast, get_args

import typer
from rich.console import Console
from rich.table import Table

from ticket_to_record import __version__
from ticket_to_record.config import ProviderName, load_settings
from ticket_to_record.eval.score import Report, score_run
from ticket_to_record.llm import build_llm
from ticket_to_record.models import ExtractionResult, LabelledTicket
from ticket_to_record.pipeline.extract import extract_many, load_tickets, write_results
from ticket_to_record.synth.generate import generate

PROVIDERS: tuple[str, ...] = get_args(ProviderName)

app = typer.Typer(add_completion=False, help="Turn free-text service tickets into records.")
console = Console()


@app.command()
def version() -> None:
    """Print the version and exit."""
    console.print(__version__)


@app.command()
def extract(
    input_path: Annotated[
        Path,
        typer.Option("--input", "-i", exists=True, dir_okay=False, readable=True),
    ] = Path("examples/tickets.jsonl"),
    provider: Annotated[
        str | None,
        typer.Option("--provider", "-p", help=f"One of: {', '.join(PROVIDERS)}"),
    ] = None,
    output_path: Annotated[
        Path | None,
        typer.Option("--output", "-o", dir_okay=False),
    ] = None,
    show: Annotated[bool, typer.Option("--show/--no-show")] = True,
) -> None:
    """Extract structured records from a JSONL file of tickets."""
    settings = load_settings()
    if provider is not None:
        if provider not in PROVIDERS:
            raise typer.BadParameter(
                f"must be one of: {', '.join(PROVIDERS)}", param_hint="--provider"
            )
        settings.provider = cast(ProviderName, provider)

    llm = build_llm(settings)
    tickets = load_tickets(input_path)

    results: list[ExtractionResult] = []
    failures: list[tuple[str, str]] = []
    for ticket, result, error in extract_many(tickets, llm):
        if result is None:
            failures.append((ticket.ticket_id, error or "unknown error"))
        else:
            results.append(result)

    if show:
        _render(results, provider=llm.name, model=llm.model)

    if output_path is not None:
        written = write_results(results, output_path)
        console.print(f"[green]wrote[/green] {written} rows to {output_path}")

    console.print(
        f"[bold]{len(results)}/{len(tickets)} extracted[/bold] via {llm.name}:{llm.model}"
        + (f" — [red]{len(failures)} failed[/red]" if failures else "")
    )
    for ticket_id, message in failures:
        console.print(f"  [red]{ticket_id}[/red]: {message}")

    if failures:
        raise typer.Exit(code=1)


def _render(results: list[ExtractionResult], *, provider: str, model: str) -> None:
    table = Table(title=f"{provider}:{model}")
    for column in ("ticket", "category", "action", "urgency", "model#", "serial", "unsupported"):
        table.add_column(column, overflow="fold")

    for item in results:
        record = item.record
        table.add_row(
            item.ticket_id,
            record.issue_category.value,
            record.requested_action.value,
            record.urgency.value,
            record.product_model or "-",
            record.serial_number or "-",
            ", ".join(item.unsupported_fields) or "-",
        )
    console.print(table)


@app.command()
def synth(
    count: Annotated[int, typer.Option("--count", "-n", min=1)] = 200,
    seed: Annotated[int, typer.Option("--seed", "-s")] = 0,
    output_path: Annotated[Path, typer.Option("--output", "-o", dir_okay=False)] = Path(
        "examples/labelled.jsonl"
    ),
) -> None:
    """Generate labelled synthetic tickets."""
    items = generate(count, seed=seed)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(item.model_dump_json() + "\n")

    tally = Counter(note for item in items for note in item.notes)
    console.print(f"[green]wrote[/green] {len(items)} labelled tickets to {output_path}")
    for note, n in sorted(tally.items(), key=lambda pair: -pair[1]):
        console.print(f"  {note:<24} {n:>4}  ({100 * n / len(items):.0f}%)")


@app.command()
def evaluate(
    input_path: Annotated[
        Path | None,
        typer.Option("--input", "-i", exists=True, dir_okay=False, readable=True),
    ] = None,
    count: Annotated[int, typer.Option("--count", "-n", min=1)] = 200,
    seed: Annotated[int, typer.Option("--seed", "-s")] = 0,
    provider: Annotated[str | None, typer.Option("--provider", "-p")] = None,
    workers: Annotated[int, typer.Option("--workers", "-w", min=1, max=32)] = 1,
    retries: Annotated[int, typer.Option("--retries", min=0, max=5)] = 0,
    repeat: Annotated[int, typer.Option("--repeat", min=1, max=20)] = 1,
) -> None:
    """Score an extraction run against labelled tickets.

    With no --input, generates a labelled set on the fly. That keeps the
    command runnable on a fresh clone with no key and no data files, which is
    the difference between a harness people use and one they read about.

    ``--repeat`` runs the whole thing N times and reports each field's mean and
    range instead of one number. It exists because temperature 0 does not make
    a provider deterministic: on 50 real tickets, six identical runs put
    `under_coverage` anywhere between 69.4% and 77.6%. A single run is a draw
    from that spread, and reporting it as a measurement invites the reader to
    compare two numbers that differ by less than the noise -- which is exactly
    the mistake this option was written after making.
    """
    settings = load_settings()
    if provider is not None:
        if provider not in PROVIDERS:
            raise typer.BadParameter(
                f"must be one of: {', '.join(PROVIDERS)}", param_hint="--provider"
            )
        settings.provider = cast(ProviderName, provider)

    if input_path is None:
        labelled = generate(count, seed=seed)
    else:
        labelled = [
            LabelledTicket.model_validate_json(line)
            for line in input_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    llm = build_llm(settings)
    reports: list[Report] = []
    tokens_in = tokens_out = 0
    for round_number in range(repeat):
        results: dict[str, ExtractionResult] = {}
        failures = 0
        for _ticket, result, _error in extract_many(
            (item.ticket for item in labelled), llm, workers=workers, retries=retries
        ):
            if result is None:
                failures += 1
            else:
                results[result.ticket_id] = result
                tokens_in += result.input_tokens or 0
                tokens_out += result.output_tokens or 0
        reports.append(
            score_run(labelled, results, failures=failures, provider=llm.name, model=llm.model)
        )
        if repeat > 1:
            console.print(f"[dim]run {round_number + 1}/{repeat} done[/dim]")

    _render_report(reports[0])
    if repeat > 1:
        _render_spread(reports)
    # Printed because a run that costs money should say what it cost, in the
    # units the invoice is in. A rate is deliberately not applied here: prices
    # change, and a stale multiplier in the source reads as authoritative.
    if tokens_in or tokens_out:
        console.print(
            f"[dim]{tokens_in:,} input + {tokens_out:,} output tokens "
            f"over {len(results):,} extractions[/dim]"
        )


def _render_spread(reports: list[Report]) -> None:
    """Mean and range per field across identical runs.

    The range is the point. Temperature 0 is widely treated as "deterministic",
    and it is not: identical input, six runs, and `under_coverage` landed
    anywhere in an 8.2-point band while `serial_number` did not move at all.
    The fields that move are the ones needing a judgement; the fields pinned to
    a verbatim string do not.

    So a single-run table is a draw, and two single-run tables cannot be
    compared unless they differ by more than this column.
    """
    table = Table(title=f"{len(reports)} identical runs — is the number stable?")
    for column in ("field", "n", "mean", "min", "max", "spread", "constant", "mean lift"):
        table.add_column(column, justify="left" if column == "field" else "right")

    for name in reports[0].fields:
        scores = [r.fields[name].score for r in reports if r.fields[name].n]
        if not scores:
            continue
        entry = reports[0].fields[name]
        spread = max(scores) - min(scores)
        mean = sum(scores) / len(scores)
        # Red when the spread is wider than a couple of points: at that width
        # any comparison between two single runs of this field is noise.
        width = f"{spread:.1%}"
        table.add_row(
            name + (" *" if entry.soft else ""),
            str(entry.n),
            f"{mean:.1%}",
            f"{min(scores):.1%}",
            f"{max(scores):.1%}",
            f"[red]{width}[/red]" if spread > 0.02 else width,
            "—" if entry.soft else f"{entry.baseline:.1%}",
            "—" if entry.soft else f"{mean - entry.baseline:+.1%}",
        )
    console.print(table)
    console.print(
        "[dim]spread is max minus min over identical runs. A difference between two "
        "single runs smaller than this is not a result.[/dim]"
    )


def _render_report(report: Report) -> None:
    table = Table(title=f"{report.provider}:{report.model}")
    for column in ("field", "n", "score", "baseline", "lift", "fabricated", "missed", "wrong"):
        table.add_column(column, justify="left" if column == "field" else "right")

    # A field nobody labelled has no score, and printing `0.0%` for it says the
    # opposite. Real evaluation sets are ragged -- the sandbox set labels six of
    # the nine fields -- so this is the normal case, not an edge one, and the
    # unlabelled fields are named underneath rather than dropped silently.
    unlabelled = [name for name, entry in report.fields.items() if entry.n == 0]

    for name, entry in report.fields.items():
        if entry.n == 0:
            continue
        # A field whose lift over the best constant answer is nil is doing no
        # work, however high its score looks. Flagging it in the table is the
        # only way that reads at a glance.
        nullable = entry.kind.value in ("exact", "date", "flag")
        lift = f"{entry.lift:+.1%}"
        if entry.lift <= 0.0:
            lift = f"[red]{lift}[/red]"
        table.add_row(
            name + (" *" if entry.soft else ""),
            str(entry.n),
            f"{entry.score:.1%}",
            "—" if entry.soft else f"{entry.baseline:.1%}",
            "—" if entry.soft else lift,
            str(entry.fabricated) if nullable else "—",
            str(entry.missed) if nullable else "—",
            str(entry.wrong_value),
        )
    console.print(table)
    console.print(
        "[dim]* scored by overlap, not exact match; no constant baseline is meaningful[/dim]"
    )
    if unlabelled:
        console.print(f"[dim]not labelled in this set: {', '.join(unlabelled)}[/dim]")
    console.print(
        f"[bold]{report.extracted}/{report.tickets} extracted[/bold]"
        + (f" — [red]{report.failed} failed[/red]" if report.failed else "")
        + f" — hallucinated on {report.hallucinated}"
        f" ({report.hallucination_rate:.1%}) of extractions"
    )


if __name__ == "__main__":  # pragma: no cover
    app()
