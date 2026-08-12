# ticket-to-record

Turn free-text service tickets into structured records.

Support inboxes produce prose; the systems downstream need fields. This repo is
the pipeline between the two, plus — and this is the part that matters — the
harness that measures whether it is actually any good.

> **Status: scaffold.** The extraction path runs end to end today against
> synthetic tickets. The synthetic generator, the evaluation harness, and
> retrieval are the next three pieces. See [Roadmap](#roadmap).

## Quick start

No API key needed. The default provider is a deterministic rule-based extractor.

```bash
make install
make run
```

```bash
# Against a real model
export GEMINI_API_KEY=...
uv run ttr extract --provider gemini --output runs/first.jsonl
```

## What it does

```
tickets.jsonl ──▶ prompt ──▶ provider ──▶ ExtractedRecord ──▶ results.jsonl
                              (fake │ gemini)
```

`ExtractedRecord` is deliberately narrow: model designation, serial, purchase
date, issue category, symptom, requested action, urgency, parts mentioned,
coverage status — and `evidence`, a list of spans copied verbatim out of the
ticket.

## Three decisions worth knowing about

**The rule-based extractor is a baseline, not a mock.** "The model gets 84%"
means nothing on its own. "The model gets 84% where regular expressions get 61%"
is a result. Every provider implements the same one-method protocol, so the
comparison is apples to apples, and the whole test suite runs with no key and no
spend.

**The model has to cite itself.** Every extracted value must come with the span
it was copied from. That turns hallucination into something countable — if a
serial number does not appear in any evidence span, the extractor invented it —
without needing a second model to act as judge.

**Ticket bodies are untrusted input.** Anyone can email a support address. The
body is fenced and labelled as data in the prompt, and `examples/tickets.jsonl`
includes a ticket that tries to talk the extractor into approving a refund.

The rule-based baseline is currently **fooled by it** — the word "refund"
appears, so "refund" is the answer, because keyword matching has no concept of
instruction versus data. That result is asserted in
`tests/test_pipeline.py::TestPromptInjection` rather than papered over. It is a
measured weakness of the cheap extractor and one of the concrete things a
language model has to beat.

## Layout

```
src/ticket_to_record/
  models.py            extraction schema + result envelope
  prompts.py           all prompt text, in one reviewable place
  config.py            environment-driven settings
  llm/base.py          the provider protocol — one method wide
  llm/fake.py          deterministic rule-based baseline
  llm/gemini.py        schema-enforced structured output
  pipeline/extract.py  ticket in, record out
  cli.py               ttr extract
scripts/redline_scan.py  pre-commit content guard
examples/tickets.jsonl   synthetic tickets, hand-written
```

## Development

```bash
make check   # lint, types, tests, red-line scan — the same set CI runs
```

`make install` also installs the pre-commit hook. The hook blocks credentials,
contact details, and data files outside `examples/`. Copy
`.redline-terms.example` to `.redline-terms` to add names that must never be
committed; that file is gitignored on purpose, and
[`scripts/redline_scan.py`](scripts/redline_scan.py) explains why hashing them
would not be a fix.

## Roadmap

| | |
|---|---|
| Synthetic ticket generator | a designed distribution, not six hand-written examples |
| Evaluation harness | labelled set, per-field accuracy, regression runs between prompt versions |
| Retrieval | grounding extraction in prior resolved tickets |
| Batch pipeline | concurrency, retries, cost and latency accounting per run |
| Anomaly detection | tickets that do not look like anything seen before |

A design write-up covering the trade-offs behind each of these will land with
the evaluation harness — numbers first, prose second.
