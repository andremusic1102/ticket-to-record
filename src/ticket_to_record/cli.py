"""Command line entry point."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast, get_args

import typer
from rich.console import Console
from rich.table import Table

from ticket_to_record import __version__
from ticket_to_record.config import ProviderName, load_settings
from ticket_to_record.llm import build_llm
from ticket_to_record.models import ExtractionResult
from ticket_to_record.pipeline.extract import extract_many, load_tickets, write_results

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


if __name__ == "__main__":  # pragma: no cover
    app()
