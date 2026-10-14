# The Claim Gate

The safety argument for this system. Its distinctive check is a different
*shape* from the ones in the other systems here, and that difference is the
whole point.

---

## Membership versus bound

Every other gate in this repository asks a membership question:

> *Is this identifier in the evidence set? Is this figure one the engine
> computed?*

A lookup. The answer is yes or no, and "no" means invented.

This gate asks something else:

> *Is this figure **larger than the evidence permits**?*

A bound, not a lookup. The figure may be perfectly real — derived from
computed numbers, in the right units, about the right unit — and still be
wrong, because it asks for more than the measurement supports.

That shape follows from how a billing claim actually fails. **Not by
inventing a number from nothing.** By taking a defensible number and rounding
it upward, or by extending a sound argument to a unit it doesn't cover. A
provider's engineer only has to discredit the overreach to have the
legitimate part dismissed with it — and a dismissed claim does not get
re-heard.

So `rules.py` computes `recoverable_ceiling_aed` and the name is deliberate.
It is a maximum, not a target, and the terminal report says so on every run.

## The two halves of check_overclaim()

**1. An amount above the ceiling.**
`claim_amounts_in()` extracts figures the text *presents as money being
sought back* — a figure near a recovery verb, in either order. Mentioning
that a unit is allocated 45 RT is not asking for 45 back, so the extraction
is scoped to claim language rather than to every number.

Each extracted amount is compared to the computed ceiling. Above it, held.

**2. Claim language attached to a unit with no finding.**
This is the harder half. A unit the engine marked `INSUFFICIENT_EVIDENCE`
has no finding — not a weak one, none. Those units are excluded from
`facts()` entirely, so an agent never sees them. The gate blocks claim
language naming them anyway, because defence that depends on information
never being presented is defence that breaks the first time someone changes
what gets presented.

The check is scoped to claim language, not mention. A draft saying *"UNT-0104
has only two months of data and needs a full season"* is honest and passes.
*"UNT-0104 is also over-allocated and a refund is due"* does not.

## Why the engine refuses first

The gate is the second line. The first is arithmetic that declines to produce
a finding at all:

- **A window that cannot have seen the peak produces nothing.** Capacity is
  sized for peak demand, and peak demand here is a summer phenomenon. A
  dataset missing summer can only show a unit was idle in winter.
- **A reading without a peak figure is not evidence.** Consumption measures
  how much cooling was used over a month; the charge is sized on the highest
  instantaneous draw. A flat heavy month and a month with one brief spike can
  have identical RT-hours and very different peaks.
- **Justified demand is peak *plus headroom*.** Claiming down to exactly
  observed peak argues a system should carry no margin for a hotter year,
  equipment ageing, or simultaneous draw. That argument loses.
- **Under-allocation is reported too**, though acting on it raises the
  client's charge. A tool that reported only the profitable direction would
  be an advocate, not a measurement — and would be worth correspondingly
  less when a provider pushed back.

## Every path to `held`

1. Any agent failing.
2. A truncated reply (`stop_reason == "max_tokens"`, checked explicitly).
3. A unit not in this review.
4. **A claim above the ceiling, or claim language on a unit with no finding.**
5. A figure nothing computed.
6. The reviewer recommending `hold`.

Overclaim is checked **before** bare figures: it is the failure that loses
the case. A test asserts that ordering.

> **The gate can only move toward `held`.** No branch releases a claim the
> reviewer did not recommend releasing, and no path back from held.

## What it does not catch

- **An overclaim written without claim vocabulary.** "The position on
  UNT-0101 amounts to 300,000 AED" dodges the verb list. The extraction is
  pattern-based and evadable, like every such filter.
- **A claim at the ceiling that the evidence nonetheless won't support in
  argument.** The ceiling is arithmetic; whether a provider accepts the
  headroom factor is a negotiation.
- **Whether the headroom factor is right.** It is an engineering judgement
  sitting in a config file, and it moves every ceiling in the portfolio. It
  carries a source pointer and a verify list for that reason.
- **Whether the metered peaks are trustworthy.** Garbage in, confident
  garbage out — the system checks the *shape* of the evidence window, not the
  calibration of the meters that produced it.

## The failure mode that looks exactly like the gate working

Thinking is on by default on the configured model, and `max_tokens` caps
thinking and response text together. A cap tight enough to truncate the JSON
produces a parse error, which the gate turns into a hold — so *every* claim
holds and the run reads as the gate working rather than the budget being
wrong.

`MAX_TOKENS = 16000`, `stop_reason == "max_tokens"` raised as itself, and a
test asserting both the floor and that the value reaches every request.
