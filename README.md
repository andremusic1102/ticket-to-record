# ticket-to-record

Turn free-text service tickets into structured records.

Support inboxes produce prose; the systems downstream need fields. This repo is
the pipeline between the two, plus — and this is the part that matters — the
harness that measures whether it is actually any good.

> **Status.** The pipeline runs end to end against synthetic tickets and against
> a redacted set of ~2,500 real ones from a production ERP. The numbers below are
> real. Retrieval and batch execution are next; see [Roadmap](#roadmap).

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
`tests/test_pipeline.py::TestPromptInjection` rather than papered over.

---

## What should not use a language model

Most of this pipeline. The model is one call in the middle of it, and the
sharpest design decisions were about keeping work away from it.

| Job | Where it runs | Why not the model |
|---|---|---|
| Removing identifying content | A projection inside the source database | A model cannot be part of the control that decides what a model is allowed to see. Sending text to an LLM to find the PII in it is sending the PII. |
| Deciding what counts as a ticket | Deterministic text normalisation | The input a label was written against and the input the model is shown must be the same string, produced by the same function. If a model decided the boundary, the accuracy number would measure that decision. |
| Scoring | Plain comparison, per field | A judge model has its own error rate, and it is correlated with the error rate of the thing being judged. Verbatim-copy fields can be checked exactly; the rest are checked by overlap and labelled as such. |
| Detecting hallucination | String containment against evidence spans | Free, deterministic, and it cannot be talked out of its answer. |
| Choosing the analysis window | SQL, on process metadata | See below. This one is not a modelling problem at all and treating it as one produces a model that learns an SOP change. |

What the model *is* for: reading a sentence like *"my customers name is …, the unit
number is …"* and knowing which of those is the serial. Regular expressions get
that wrong 608 times in 2,543 tickets — details below.

---

## The data only remembers outcomes that cost money

This is the finding that shaped everything else, and it generalises past this
one system.

An approved claim generates a sales order: parts move, money is spent,
and the event is written down in three places because Finance needs it. A denied
claim generates nothing. Nobody downstream is waiting for it, so it is recorded
nowhere except in the sentence an agent typed into a message body.

Probing twelve denial phrases against message **subjects** returned between 0
and 14 hits each. The same phrases against message **bodies** returned ten to a
hundred times more. The outcome exists; the *record* of it does not.

Three consequences:

* **Historical labels cannot train or evaluate a classifier here.** The label set
  is one-sided by construction, and a model trained on it learns that claims are
  approved.
* **A keyword search of the bodies is not a substitute.** It was tested rather
  than assumed: of five denial phrases, one was reliable, and the worst matched
  the substring inside *incline* and *declining*. A fourth appears as boilerplate
  inside the **approval** template — sampling negatives on it would have built a
  set whose negatives were positives.
* **The reliable signal was structural, and nobody had gone looking for it.**
  Reading thirty tickets turned up two templated denial notices covering 120
  cases in the window — machine-checkable, no keyword guessing.

The general form: *before mining a field for outcomes, ask what happens
downstream when the outcome is negative. If the answer is "nothing", the field
records one class.*

---

## Find the process breaks before choosing a window

The dataset spans 28,000 cases and several years. Training or evaluating across
all of it would be a mistake, and not because of drift in the ordinary sense.

Two process changes are visible in the data itself:

* the templated approval notice — the only reliable outcome marker — **does not
  exist before 2024**;
* intake changed at the end of the observation period: volume **tripled** and the
  proportion of cases carrying a triage type fell from **76% to 13%** in a single
  month.

So the analysis window is one eleven-month stretch that sits inside a single
process regime. A model measured across the boundary would be scored on an SOP
change and the error would be attributed to the model.

Finding those breaks took two queries. Not finding them would have cost the
credibility of every number afterwards.

---

## Measuring it

```bash
uv run ttr evaluate --provider fake        # no key, no data files needed
```

Two evaluation sets, and they are reported separately because their denominators
differ by fifty-fold.

**Hand-labelled, 50 real tickets, six fields.** Sampled in six strata rather than
at random — the human-tagged in-scope cases, the templated approvals and denials, and
a deliberate over-sample of the cases where the serial is *not* stated in the
text, because those are the hard ones and a random draw would decide how many
appeared.

Every model number is a **mean over five identical runs**, with the range,
because a single run is a draw rather than a measurement — see below.

| Field | n | model (mean) | min–max | rules | constant | mean lift |
|---|---:|---:|---:|---:|---:|---:|
| `product_model` | 47 | **88.9%** | 87.2–89.4 | 55.3% | 55.3% | **+33.6%** |
| `serial_number` | 49 | **97.6%** | 95.9–98.0 | 79.6% | 77.6% | **+20.0%** |
| `purchase_date` | 49 | 98.0% | 98.0–98.0 | 71.4% | 93.9% | +4.1% |
| `issue_category` | 47 | **78.3%** | 74.5–80.9 | 27.7% | 59.6% | **+18.7%** |
| `under_coverage` | 49 | 75.5% | 69.4–79.6 | 79.6% | 79.6% | **−4.1%** |
| `parts_mentioned` | 47 | 67.1% | 65.9–68.3 | 16.0% | — | — |

The `rules` column has no range: it is deterministic. The model column is not,
and that is the next section.

**Automatically scored, 2,543 real tickets, one field.** A serial appears both in
the ticket text and in a structured column, so it can be scored at scale with no
hand labelling — but only 629 of the 2,543 state one. The other 1,914 are not
filler: the correct answer is `null`, and they are the only thing here that
measures abstention.

| Field | n | model | rules | constant | lift over constant |
|---|---:|---:|---:|---:|---:|
| `serial_number` | 2,530 | **95.3%** | 74.6% | 75.2% | **+20.0%** |

Thirteen calls failed after three retries and are scored as neither right nor
wrong. The two extractors fail in opposite characters, which one number would
have hidden:

| | fabricated | missed | wrong |
|---|---:|---:|---:|
| rules | 35 | 2 | 608 |
| model | **95** | 5 | 20 |

The keyword extractor nearly always finds *a* serial and takes the wrong token
608 times. The model gets the value right when there is one — and invents a
serial in **95 of the 1,914 tickets that state none**, three times the
baseline's fabrication rate, on a task whose prompt says to return null rather
than guess.

That number is only visible because three quarters of the set has no answer to
find. An evaluation built only from cases that *have* answers cannot see
fabrication at all: there is nothing to fabricate into.

Three columns exist because an accuracy number without them misleads.

**`constant` is the best fixed answer for that field.** Most tickets do not state
a purchase date, so answering null every time — reading nothing, thinking nothing
— scores 93.9%. Any field whose lift is zero or negative is printed in red.

**`n` is per field and never averaged.** One blended number across a 49-ticket
field and a 2,543-ticket field hides a difference of that size, so there isn't
one.

**The failure columns separate three different mistakes.** A value invented where
none existed, a value missed that was there, and a value found but wrong are a
data-integrity problem, a coverage problem and a quality problem — different
owners, different fixes. Collapsing them into "24% wrong" throws away the part an
engineer would act on.

Failed provider calls are counted separately and scored as neither right nor
wrong. Marking them wrong blames the model for an outage; dropping them reports
accuracy for the subset that happened to succeed.

---

## Failure modes, including the ones that are still open

**Temperature 0 is not reproducibility, and finding that out invalidated a
comparison I had already made.** Identical input, same model, five runs:

| Field | spread over 5 identical runs |
|---|---:|
| `purchase_date` | **0.0** |
| `serial_number` | 2.0 |
| `product_model` | 2.1 |
| `parts_mentioned` | 2.4 |
| `issue_category` | 6.4 |
| `under_coverage` | **10.2** |

The fields pinned to a verbatim string do not move; the fields needing a
judgement do, and the widest is the one where the judgement is hardest. Two
labels were corrected during review, the score moved two points, and that move
was reported as an effect of the correction — it is a third of the field's
run-to-run range and means nothing. `ttr evaluate --repeat N` now reports mean
and range, and a comment in `config.py` claiming temperature 0 made the harness
reproducible has been corrected.

**The model loses to a constant on one field, and the loss survives the spread.**
`under_coverage` averages 75.5% against 79.6% for answering `null` every time.
Across eleven runs it never beat that constant and tied it once — which is the
only sort of claim a set this size can carry. It errs in both directions: it
abstains where coverage is stated, and it asserts coverage where the ticket
merely *asks* about it, though the prompt tells it not to infer.

This is left as measured. Changing the prompt and re-reporting the higher number
would be reporting a number chosen after seeing the answer.

**One field cannot be measured on this set at all.** `purchase_date` has three
positives in forty-nine. A model that finds two of three and invents nothing
scores 96%, one point over a constant — and the difference is one ticket.
Reported as a count, not a rate.

**Synthetic data flattered the cheap baseline.** On generated tickets the
rule-based extractor scored 64.5% / 30.0% / 86.0% on model, serial and date. On
real ones it scores 55.3% / 79.6% / 71.4% — *and on two fields it is worse than
answering null*. Serial extraction turned out easier on real tickets, because
real serials arrive in a few stereotyped phrasings while the generator had been
given eight deliberately. Everything else got harder. A generator makes a
baseline look like a floor; it is not one.

**A quarter of the "tickets" are forms.** 27% of the window arrives as
`Symptom of Failure : …` key-value pairs rather than prose. Extraction from a
form is parsing. A single number over a mixed set averages two different tasks,
so the split is reported.

**The business's own vocabulary does not span its own tickets.** Problem
categories are extracted into a component taxonomy that already existed in the
source system rather than one invented for the demo — which is the stronger
claim, except that 25 of the 50 tickets map to none of its values, because the
taxonomy names a handful of mechanical and electrical subsystems while the
tickets are about bodywork, missing hardware and short shipments.

---

## Two lessons about verification, which cost more than the pipeline did

The extraction side of this project is a number that goes up. The perimeter side
either leaks or it does not, and it can be attacked. That asymmetry produced the
only genuinely adversarial testing in the project, and both lessons generalise.

**A probe written from the same premise as the thing it tests is not a test.**
The redaction layer's phone pattern required punctuation in two positions. So did
the probe that verified it. Ten digits punctuated *once* passed straight through
both, and no amount of before-and-after measurement on that side could ever have
shown it — the check and the code shared a blind spot because one author wrote
both from one assumption. It took re-running everything in a second regex engine,
with patterns written in a different dialect, to find real numbers surviving.
The same thing happened three times in one day, in three different places.

**Systematic sampling aliases, and the failure looks like a broken system.**
Sampling with `MOD(id, N) = 0` is standard and cheap. On the same population,
three strides of nearly the same sample size:

| stride | n | bodies containing a punctuated phone |
|---:|---:|---:|
| 397 | 69 | 8.7% |
| **400** | **59** | **0.0%** |
| 401 | 75 | 12.0% |

Zero, for a shape present in roughly one body in eight. A verification run on
stride 400 reports that its probes have no power and reads as a broken check on
a broken layer. Round strides alias with whatever structure the ids carry; the
sampler now refuses anything but a prime.

The corollary that runs through both: **a check that cannot fail proves nothing,
and a check that fails for the wrong reason teaches its reader to ignore it.**
Every residual probe here runs twice — once against the unmasked text to prove it
has something to find, once after — and reports `NO POWER` rather than success
when the before-count is zero. Probes for shapes too rare to sample for are
measured once, recorded, and deliberately left out of the routine run.

---

## Layout

```
src/ticket_to_record/
  models.py            extraction schema + result envelope
  prompts.py           all prompt text, in one reviewable place
  config.py            environment-driven settings
  llm/base.py          the provider protocol — one method wide
  llm/fake.py          deterministic rule-based baseline
  llm/gemini.py        schema-enforced structured output
  pipeline/extract.py  ticket in, record out; concurrency and retry
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
contact details, and data files outside `examples/`.

### On a new machine

```bash
make install
ln -s /path/to/your/term-list.txt .redline-terms   # or copy .redline-terms.example
make check
```

`.redline-terms` holds names that must never be committed and is gitignored on
purpose — [`scripts/redline_scan.py`](scripts/redline_scan.py) explains why
committing it, or hashing it, would not be a fix. A symlink to a file that syncs
between your machines is the practical form: a fresh clone is the machine most
likely to commit something careless, and it is also the one that starts without
the list.

The scan **fails** rather than passing with a note when the list is missing.
Reporting "clean" for a check that never looked is the failure mode that
matters here.

## Generating the data

```bash
uv run ttr synth --count 200 --seed 0
```

The generator's distributions are the deliverable, not the prose. Each rate is
tagged in the source as *measured* — taken from a profile of ~27,000 real service
messages — or *assumed*, so nobody later quotes a guess as a finding. Bodies
mimic already-redacted text, with tokens like `[EMAIL]` where contact details
were, because that is what this pipeline receives in production.

**One finding from building it, kept because it generalises.** The first version
scored the rule-based baseline at 100% on three fields. Not because the baseline
is good — because the generator wrote serials as "Serial number X", exactly the
pattern the baseline greps for. A generator and a baseline written by the same
hand agree with each other unless something forces them apart, and an evaluation
the baseline cannot lose measures nothing. The fix was surface variation, and
`tests/test_synth.py` now guards the regression. Note that the harness could not
have caught this: a constant-answer baseline detects majority-class bluffing, not
a test set built to the extractor's assumptions.

## Roadmap

| | |
|---|---|
| ~~Synthetic ticket generator~~ | done — `ttr synth` |
| ~~Evaluation harness~~ | done — `ttr evaluate` |
| ~~Model vs baseline on real data~~ | done — the tables above |
| Error analysis | the `under_coverage` misses first; they are one failure mode, not eleven |
| Retrieval | grounding extraction in prior resolved tickets |
| Batch pipeline | cost accounting per run, and progress output — a 2,543-ticket run currently prints nothing until it finishes |
