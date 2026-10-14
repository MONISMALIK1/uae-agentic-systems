# mizan (ميزان) — *the scales*

**The district cooling bill nobody can check.** Compares each unit's
allocated refrigeration tons against the peak demand actually metered, and
refuses to make a finding where the evidence cannot have observed the peak.

Status: working v0.1, built 2026-10-14. 47 tests, hermetic — the gate is
verified on constructed evidence and a stubbed client, so CI needs no API key.

> **Not tariff, legal or engineering advice.** The headroom factor, limitation
> period and evidence standards in `config.py` are illustrative defaults that
> exist to exercise the arithmetic. Verify them with an MEP engineer and
> against the provider's billing terms and the regulator before any claim.
> The tool prints that warning on every run.

---

## The problem

A large share of UAE cooling runs through district cooling plants, and the
bill has two parts. **Consumption** — what you used. And **capacity** — a
fixed annual charge on the refrigeration tons *allocated* to your unit,
billed whether or not you were in the country that month.

The allocated RT figure is set once, at design or handover, from the
developer's drawings — and then **never revisited**. A unit drawn as
open-plan retail and fitted out as a storage room carries the retail
allocation forever. A floor that was subdivided keeps its pre-subdivision
numbers.

The asymmetry that makes it a tool: **a consumption error shows up as a weird
month and gets queried. A capacity error shows up as a slightly-too-high
normal, forever, and never does.** Across an owners' association with a few
hundred units, the same defect is carried a few hundred times.

## What makes this different from a comparison

Comparing allocation to observed peak is easy, and it is not the product.

**The product is refusing to compare when the evidence can't carry it.** A
unit's allocation is sized for peak demand, and peak demand in this climate
happens in high summer. A dataset that doesn't span a summer cannot establish
that an allocation is oversized — it can only show the unit was idle in
winter, which is not a finding about capacity.

Claiming on that evidence is how a legitimate case dies. A provider's
engineer reads it, finds the window missed the peak season, and the whole
claim — including the sound part — is dismissed and not re-heard.

So insufficient evidence is a **hard stop**, not a caveat:

| State | Meaning |
|---|---|
| `OVER_ALLOCATED` | Allocation exceeds justified demand on a full-season window |
| `UNDER_ALLOCATED` | Observed peak exceeds the allocation — **reported honestly, though correcting it raises the charge** |
| `WITHIN_TOLERANCE` | Oversized, but not enough to be worth disputing |
| `INSUFFICIENT_EVIDENCE` | The window cannot have seen the peak. **No finding at all** |
| `NOT_ASSESSABLE` | No allocation or no rate on record — not a zero |

## The gate: a bound, not a lookup

Three checks:

- `check_citations()` — a unit not in this review.
- `check_overclaim()` — **the one this system is built around.**
- `check_figures()` — a figure nothing computed.

The middle one is a different shape from the membership checks in the other
systems here. Those ask *is this figure in the evidence set?*. This asks **is
this figure larger than the evidence permits?**

That matters because the characteristic failure of a billing claim isn't
inventing a number from nothing. It's rounding a defensible number upward
until the claim becomes contestable. So the recoverable figure is computed as
a **ceiling**, and the gate bounds every claim amount against it.

Its second half is harder: a unit the engine marked `INSUFFICIENT_EVIDENCE`
must not have claim language attached to it *at all*. The engine refused to
make a finding; the drafting layer may not manufacture one. Those units never
reach an agent, and the gate blocks claim language naming them even so.

Full reasoning: [docs/the-claim-gate.md](docs/the-claim-gate.md).

## Run it

```bash
make test
make demo-deterministic   # no API key: evidence test, justified demand, ceiling
make demo                 # full pass; needs ANTHROPIC_API_KEY
```

```bash
mizan units.csv --readings readings.csv --out review.csv
```

| flag | why |
|---|---|
| `--today YYYY-MM-DD` | pin the run date, for reproducible output |
| `--config FILE` | override evidence standards, headroom and tolerance |
| `--no-agents` | computed review only; no model calls |
| `--fail-on over-allocated\|under-allocated\|held` | exit non-zero, for a scheduled run |

## What the demo shows

Eight units across three buildings, 14 months of metered peaks:

```
  OVER_ALLOCATED  (3)
    !! OVER-ALLOCATED  UNT-0101  Marina Heights  alloc 45.0 RT  peak 18.7 RT  ceiling 225,600.00
          - 45 RT allocated against 21.5 RT justified -- 23.5 RT of excess
          - 75,200.00 AED per year; 225,600.00 AED over 3 year(s) is the
            CEILING a claim may assert, not a target

  INSUFFICIENT_EVIDENCE  (1)
    ?  no finding yet   UNT-0104  Marina Heights  alloc 18.0 RT  peak -- RT
          - only 0 of the observed month(s) fall in the cooling peak season --
            a window that has not seen summer cannot establish that an
            allocation is oversized, it can only show the unit was idle in winter

  recoverable ceiling across the portfolio: 444,106.50 AED
  that figure is a CEILING, not a target
```

Four things in that output are why the tool exists:

- **`UNT-0101` is allocated at 2.4× its justified demand** and has been
  billed for it every month since handover. Nothing ever flagged it, because
  it never looked anomalous.
- **`UNT-0104` gets no finding.** Five winter months. The allocation may well
  be wrong, and the honest output is "collect a season first."
- **`UNT-0103` is reported as under-allocated** — a finding that *costs* the
  client money to act on. Reporting only the profitable direction would make
  the tool an advocate rather than a measurement.
- **Justified demand is peak plus headroom, not peak.** Claiming down to
  exactly observed peak argues a system should be sized with no margin for a
  hotter year or ageing plant. That argument loses and takes the rest with it.

## Limits

- **Config figures are illustrative.** Stated above, printed every run.
- **Peak demand must be metered.** Consumption (RT-hours) cannot substitute:
  a flat heavy month and a month with one brief spike can have identical
  RT-hours and very different peaks. A reading without a peak figure doesn't
  count as evidence, which is strict and is the point.
- **The tolerance and headroom factors are judgements**, not rules. They
  decide which units are worth disputing, and a provider will argue about
  both.
- **`released` means "recommended by this tool," not "submitted."** Nothing
  here contacts a provider or a regulator.

## Layout

```
src/mizan/
  rules.py      ALL arithmetic: evidence test, justified demand, the ceiling
  agents.py     explainer, claim drafter, reviewer, and the Claim Gate
  config.py     evidence standards, headroom, tolerance -- all on a verify list
  units.py      allocation schedule and monthly readings; a gap is never a zero
  report.py     terminal view + the review CSV
  cli.py
examples/       8 units, 14 months of seasonal peaks: a badly oversized retail
                unit, one within tolerance, one under-allocated, one with a
                winter-only window, and one with no allocation on record
docs/           the claim-gate argument
tests/          measurement arithmetic, gate logic, and an end-to-end CI guard
```
