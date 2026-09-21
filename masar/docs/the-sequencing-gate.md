# The Sequencing Gate

The safety argument for this system: what licenses a claim, every path to
`held`, what the gate does *not* catch, and the failure mode that looks
exactly like the gate working.

---

## The problem the gate exists for

The output of this pipeline is advice a planning engineer acts on this week:
*file this now, defer that one, chase this authority, expect clearance by
this date.*

Every failure mode of that advice is fluent. An invented permit number is the
right shape. **An invented date is the worst of all, because a wrong date does
not look wrong. It looks like a date.** It sits in a programme, someone plans
a concrete pour against it, and it is discovered to be wrong a month later
when the submission bounces and the upstream cycle has already been consumed.

Which would be a particularly embarrassing way to fail, because *that is the
exact failure this system exists to prevent.*

So the gate does not ask the model whether it stayed inside the evidence. It
checks.

## What licenses a claim

### An authority reference

`expand_evidence()` collects every authority file number on the project —
`BP-2026-9902`, `DEWA-2026-5510`, `DCD-2026-8812` — plus any reference
appearing in a finding's reasons, which is safe because finding text is
written by `rules.py`.

A reference is recognised bracketed or bare: a model that drops the brackets
has still made a reference.

**A bug worth recording.** The first version of this pattern was
`[A-Z]{2,6}(?:-[A-Z]{2,6})?-[A-Z0-9]*\d[A-Z0-9]*`, which matched `BP-2026`
and stopped — because a hyphen satisfies `\b`. Every legitimate reference was
therefore reported as ungrounded, and the gate would have held *every* draft.
The tests caught it immediately; a looser test suite would not have. The
current pattern matches the whole hyphenated run and filters for a digit
afterwards, which also keeps `AS-BUILT` and `FIRE-SAFETY` from reading as
references.

### A date

Only ISO dates count. `rules.py` emits dates in exactly one form, and the
agents are permitted to state them in exactly that form. Prose timing
("mid-October") states nothing checkable — it is not a violation, and it is
also not actionable, which the prompts discourage.

Licensed dates are every computed `earliest_file_date` and
`forecast_grant_date`, the forecast completion, today's date, and any date
appearing in a finding's reasons.

**There is no tolerance.** Unlike a dirham figure, where rounding to the whole
unit is a legitimate way to write the same number, a date is either the
computed one or a different day. A submission filed one day early is filed
out of sequence.

### The verdict

This is the third check and the one that makes the system coherent.
`rules.py` owns readiness. `check_verdict()` holds any draft that urges
**filing** an approval the engine marked `WILL_BOUNCE` or `BLOCKED`.

The distinction is deliberately narrow: it fires on a filing verb near an
urgency word, not on merely naming the approval. A draft saying
*"BUILDING_PERMIT is waiting on DEWA_NOC and cannot progress"* is accurate and
passes. A draft saying *"submit BUILDING_PERMIT now to save a cycle"* is
overruling a computation and is held.

That matters because the whole system exists to stop a human making exactly
that error under deadline pressure. It certainly must not be made by a model
inside the tool.

## Every path to `held`

1. **Any agent failing** — exception, refusal, parse error.
2. **A truncated reply** — `stop_reason == "max_tokens"`, checked explicitly.
3. **A reference the project does not carry** — `check_references()`.
4. **A date no computation produced** — `check_dates()`.
5. **Advice to file something unfilable** — `check_verdict()`.
6. **The reviewer recommending `hold`.**

And the invariant:

> **The gate can only move a project toward `held`.** There is no branch that
> sets `status = "released"` on a project whose reviewer recommended holding,
> and no path from `held` back to `released`.

Checks run in fixed order — references, dates, verdict, then the reviewer's
own recommendation — because a reference that does not exist is the first
thing an engineer would go and look up, and the report names only the first
failure found.

## What the gate does not catch

- **A true reference attached to a false characterisation.** The draft cites
  `DEWA-2026-5510`, which exists, and describes its status wrongly. Every
  reference is real and the sentence is wrong. The gate is reference-shaped
  and date-shaped; it is not a comprehension check.
- **Omission.** A draft that simply fails to mention the bouncing submission
  passes every check. Nothing here requires completeness.
- **Whether the underlying graph is right.** If `config.py` has the wrong
  prerequisite for an authority, every verdict downstream is internally
  consistent and externally wrong. This is why every entry carries a source
  pointer and sits on a verify list the report prints on every run — and it
  is the single biggest real-world risk in this system.
- **Whether the advice is *good*.** Sequencing is a judgement call with
  commercial context the tool cannot see. The tool's job ends at a
  recommendation.

Those gaps are why `released` means *recommended*, and why nothing here
transmits anything to an authority.

## The failure mode that looks exactly like the gate working

Thinking is on by default on the configured model, and `max_tokens` caps
thinking and response text **together**.

Set that cap too tight and the JSON reply truncates mid-object. That surfaces
as a parse error, which is caught and turned into a `held`. Every project in
the run is held, with a reason that reads like the gate correctly refusing to
trust anything — and the run looks *safe*. It is not safe; it is broken, in
the direction that produces no alarm.

Three things close it, from the first commit:

- `MAX_TOKENS = 16000`, with the reason written beside it.
- `stop_reason == "max_tokens"` raised as itself, never as a parse error.
- A test asserting `MAX_TOKENS >= 8000` and that the value reaches every
  request, so the budget cannot quietly drift back down.

`stop_reason == "refusal"` is checked *before* `resp.content` is read: on a
refusal the content list is empty or partial, so reading it first raises the
wrong error and hides what happened.

## Why the tests are hermetic

Every test runs on constructed evidence and a stubbed client. No API key, no
network, no model. The guarantee being tested is *"an invented date is held"*,
and that must not depend on how a model behaves on a particular day. CI
asserts the gate, not the weather.

The stub routes by **schema shape**, not by matching text in the system
prompt — a wrapped docstring can split a matched phrase across two lines and
send every call to the wrong branch.
