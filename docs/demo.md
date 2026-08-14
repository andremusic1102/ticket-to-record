# Five minutes

A walkthrough for someone who has not seen this repository. Every command below
runs **with no API key and no network** — the default provider is the
deterministic baseline, and the real-data numbers are quoted from the README
rather than re-measured live. A demo that can hit a rate limit is a demo that
will.

Total: about five minutes, of which two are talking.

```bash
make install    # once, beforehand
make demo       # runs steps 1 and 2 back to back
```

---

## 1 — What it does (45s)

```bash
uv run ttr extract --provider fake
```

Six tickets in, six structured records out. Point at one record: model
designation, serial, purchase date, category, parts, coverage — and `evidence`,
the spans each value was copied from.

> "The interesting half isn't the extraction. It's that every value comes with
> the span it came from, so hallucination is countable without a second model
> judging the first one."

## 2 — The number that isn't a number (75s)

```bash
uv run ttr evaluate --provider fake
```

Point at the **`baseline`** column, not the score.

> "That column is what you get by reading nothing and answering `null` every
> time. Purchase date scores 69% that way. If I reported 86% without it, a
> 17-point result would sound like an 86-point one. Any field where the lift is
> zero, the system isn't doing work on — and it prints in red."

Then the `fabricated / missed / wrong` columns:

> "Three different mistakes with three different owners. A value invented, a
> value missed, a value found but wrong. Collapsing them into '24% wrong' throws
> away the part an engineer would act on."

## 3 — The defect worth showing (60s)

Scroll to **Generating the data** in the README.

> "The first version of the generator scored the keyword baseline at 100% on
> three fields. Not because it's good — because the generator wrote serials as
> `Serial number X`, which is exactly what the baseline greps for. A generator
> and a baseline written by the same person agree with each other unless
> something forces them apart.
>
> The harness could not have caught it. A constant-answer baseline detects
> majority-class bluffing, not a test set built to the extractor's own
> assumptions. Reading the output caught it."

`tests/test_synth.py` guards the regression. This is the strongest thing in the
repo to show, because it is a mistake that was found and kept rather than
quietly fixed.

## 4 — Untrusted input (30s)

`examples/tickets.jsonl` contains a ticket that tries to talk the extractor into
approving a refund.

> "The baseline is fooled — 'refund' appears, so 'refund' is the answer. That's
> asserted in a test rather than papered over. It's a measured weakness of the
> cheap extractor and one of the concrete things a model has to beat."

## 5 — Real data (90s)

The two tables in **Measuring it**. Do not re-run them.

> "Fifty hand-labelled real tickets from a production ERP, and 2,543 scored
> automatically on one field where a structured column gives the answer for
> free. Reported separately, because one number over both would hide a
> fifty-fold difference in sample size.
>
> Two things I'd want you to notice. The model beats the keyword baseline
> everywhere — and on one field it loses to *answering null every time*. Eleven
> misses, two fabrications: it abstains where coverage is stated far more often
> than it invents coverage where it isn't. That's the safe direction and it's
> the direction the prompt pushes. I left it as measured, because changing the
> prompt and re-reporting the better number is reporting a number I chose after
> seeing the answer.
>
> The other one: on synthetic tickets the keyword baseline looked like a floor.
> On real ones it is *below* a constant answer on two fields. Generated data
> flatters a cheap baseline."

## 6 — What isn't the model's job (60s)

The table in **What should not use a language model**.

> "Redaction runs as a projection inside the source database, not in the
> pipeline. If you strip PII in the pipeline, the raw text is already on the
> machine — the control is after the thing it prevents. And you can't use a
> model to find the PII, because sending it the text is the leak.
>
> Two lessons from that side cost more than the pipeline did. First, a probe
> written from the same premise as the thing it tests is not a test — the phone
> pattern and the probe that verified it shared a blind spot, so real numbers
> passed both, and it took a second regex engine in a different dialect to see
> it. Second, systematic sampling aliases: three strides of the same sample size
> gave 8.7%, 0.0% and 12.0% for the same shape. The zero looks like a broken
> system rather than a broken sample."

---

## If they ask for one thing

Show step 3. Anyone can produce an accuracy number; the question that separates
people is whether they know what would make theirs meaningless.

## Before this repository is public

```bash
make publish-check
```

`redline_scan.py` checks the working tree, which is the right scope for a commit
hook and the wrong one for a one-way door: publishing a repository publishes its
history, and a term deleted three commits ago is still in the pack file.
`redline_history.py` reads every blob reachable from every ref.
