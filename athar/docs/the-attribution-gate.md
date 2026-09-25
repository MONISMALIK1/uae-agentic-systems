# The Attribution Gate

The safety argument for this system. Shorter than the others, because it
reduces to a single sentence:

> **This system's output is an accusation. So it must never make one it
> cannot support.**

---

## What the output actually is

Not a report. A document that says a named person incurred a penalty, which
leads to one of two things: a card on file getting charged, or a conversation
with an employee about money taken from their wages.

Both are hard to take back. A wrongly charged renter disputes it, wins,
and leaves a review. A wrongly accused employee is a labour matter, and in
the UAE what may lawfully be deducted from wages is constrained by statute
and by the employment contract — which is why this system flags employee
attributions for a conversation rather than treating them as recoverable
money.

So the design question is not "how accurate can the join be?" It is "what
does the system do when the join is genuinely ambiguous?"

## The three-state answer

```
ATTRIBUTED      exactly one custody interval covers the violation, with
                margin on both sides of the handover buffer
CONTESTED       the data cannot settle it. NOBODY IS NAMED.
COMPANY         no interval covers it; the vehicle was ours
UNATTRIBUTABLE  the fine has no usable timestamp; it cannot be placed at all
```

**CONTESTED is the product.** Any system that resolves the ambiguous middle
by guessing produces a cleaner-looking report and a worse business, because
the guesses are discovered one at a time, expensively, by the person who was
wrongly charged.

Three things land in it:

- **The handover window.** A violation within the buffer of a custody edge
  cannot be pinned on either side. Clock skew between an authority's system
  and a fleet system is real, and a vehicle in a handover bay has no clear
  custodian. Widening that buffer only ever moves fines *into* contested —
  the knob has one safe direction, and a test asserts it.
- **Overlapping records.** Two intervals covering the same moment means the
  custody record contradicts itself. The right output is to say so.
- **A missing timestamp.** Handled in the loader, deliberately: a fine with
  an unparseable time returns `None` rather than defaulting to midnight,
  because a midnight default would silently place the violation inside
  whichever assignment spanned that hour. That is a false attribution created
  by rounding.

## What licenses a claim

### An identifier

Fine IDs, assignment IDs, driver IDs, contract and handover references — every
one that appears in the computed ledger, plus any appearing in a finding's
reasons, which is safe because reason text is written by `rules.py`.

### A figure

Every computed amount and day count, admitted to two decimals or to the whole
unit. Identifiers are stripped before figures are extracted: `ASG-00301` is a
custody record, not 301 dirhams.

### A name — and this is the check that matters

`check_naming()` holds any draft containing a driver identifier from the
**unnameable** set: every driver ID anywhere in the fleet, minus the ones the
engine actually attributed.

The subtlety worth stating: **those names are real.** `DRV-9950` really did
rent that car that morning. What is not established is that they were driving
at the moment of the violation — and the contested fine's own reasons list the
candidate assignments by ID, which is exactly the context a model would use to
infer a name. The check makes the engine's refusal unforgeable downstream.

It is scoped to identifiers, not prose. A draft saying *"ask whoever held the
vehicle that morning"* about a contested fine is honest and passes. Attaching
`DRV-9950` to it does not.

Naming is checked **before** figures, because it is the more serious failure
by a wide margin. A test asserts that ordering.

## Every path to `held`

1. Any agent failing — exception, refusal, parse error.
2. A truncated reply (`stop_reason == "max_tokens"`, checked explicitly).
3. An identifier that does not exist in this run.
4. **A driver the engine declined to attribute.**
5. A figure no computation produced.
6. The reviewer recommending `hold`.

> **The gate can only move toward `held`.** No branch releases advice the
> reviewer did not recommend releasing, and no path back from held.

## What the gate does not catch

- **A true name attached to a false characterisation.** The draft names the
  correctly attributed driver and then describes what they did wrongly.
- **Naming someone in prose without an identifier.** A draft saying "the
  gentleman who collected it at 5am" identifies a person without matching the
  ID pattern. This is a real gap. It is mitigated by the system prompts and by
  the fact that the drafting layer is given IDs rather than names to work
  with — but it is not closed, and a production version would want a
  name-matching pass over the fleet roster.
- **Whether the handover buffer is right.** Set it too narrow and real
  ambiguity is reported as certainty. It is a firm-specific estimate of that
  firm's own timestamp discipline, and it should be measured rather than
  assumed.
- **Whether the fine is valid at all.** This system attributes; it does not
  assess whether the authority was correct.

## The failure mode that looks exactly like the gate working

Thinking is on by default on the configured model, and `max_tokens` caps
thinking and response text together. A cap tight enough to truncate the JSON
produces a parse error, which the gate turns into a hold — so *every* batch
holds, and the run reads as the gate working rather than the budget being
wrong.

`MAX_TOKENS = 16000`, `stop_reason == "max_tokens"` is raised as itself, and a
test asserts both the floor and that the value reaches every request.

## Why the tests are hermetic

Constructed evidence, stubbed client, no API key, no network. The guarantee
under test is *"a name the engine refused to assert is held"*, which must not
depend on how a model behaves on a given day.
