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
  synth/generate.py    labelled tickets from a designed distribution
  eval/score.py        per-field scoring against a constant baseline
  cli.py               ttr extract | synth | evaluate
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

## Measuring it

```bash
uv run ttr evaluate --provider fake        # no key, no data files needed
```

```
field            n   score  baseline    lift  fabricated  missed  wrong
product_model  200   64.5%     26.5%  +38.0%           4      65      2
serial_number  200   30.0%      0.5%  +29.5%           0      99     41
purchase_date  200   86.0%     69.0%  +17.0%           0      28      0
issue_category 200   71.0%     19.5%  +51.5%           —       —     58
under_coverage 200   75.0%     55.5%  +19.5%           0      50      0
```

Three columns exist because an accuracy number without them misleads.

**`baseline` is the best constant answer for that field.** Most tickets do not
state a purchase date, so answering null every time — reading nothing, thinking
nothing — scores 69%. Reporting 86% without that comparison would make a
9-point-lift result sound like a 20-point one. Any field whose lift is zero is
printed in red, because a field where the system cannot beat a constant is a
field it is not doing any work on.

**`n` is per field, and never averaged across them.** Real evaluation sets are
ragged: a field checkable against a structured column can be labelled on
thousands of tickets while the rest are labelled on the fifty a human read. One
blended figure hides a difference of that size, so there isn't one.

**The failure columns separate three different mistakes.** A value invented
where none existed, a value missed that was there, and a value found but wrong
are a data-integrity problem, a coverage problem and a quality problem — with
different owners and different fixes. Collapsing them into "24% wrong" throws
away the part an engineer would act on.

Failed provider calls are counted separately and scored as neither right nor
wrong. Marking them wrong blames the model for an outage; dropping them reports
accuracy for the subset that happened to succeed.

## Generating the data

```bash
uv run ttr synth --count 200 --seed 0
```

The generator's distributions are the deliverable, not the prose. Each rate is
tagged in the source as *measured* — taken from a profile of ~27,000 real
service messages — or *assumed*, so nobody later quotes a guess as a finding.
Bodies mimic already-redacted text, with tokens like `[EMAIL]` where contact
details were, because that is what this pipeline receives in production.

**One finding from building it, kept because it generalises.** The first version
scored the rule-based baseline at 100% on three fields. Not because the baseline
is good — because the generator wrote serials as "Serial number X", which is
exactly the pattern the baseline greps for. A generator and a baseline written
by the same hand agree with each other unless something forces them apart, and
an evaluation the baseline cannot lose measures nothing. The fix was surface
variation: unlabelled identifiers, four date formats, varied prefixes. The
baseline dropped to 30–86% depending on the field, and `tests/test_synth.py`
now guards against the regression. Note that the harness could not have caught
this: a constant-answer baseline detects majority-class bluffing, not a test set
built to the extractor's assumptions.

## Roadmap

| | |
|---|---|
| ~~Synthetic ticket generator~~ | done — `ttr synth` |
| ~~Evaluation harness~~ | done — `ttr evaluate` |
| Model vs baseline | the numbers above are the floor; the point is what beats them |
| Retrieval | grounding extraction in prior resolved tickets |
| Batch pipeline | concurrency, retries, cost and latency accounting per run |

A design write-up covering the trade-offs behind each of these will land next —
numbers first, prose second.
