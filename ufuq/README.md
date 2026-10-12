# ufuq (أفق) — *horizon*

**The Emiratisation target you'll miss is already unavoidable — you just
don't know it yet.** Projects a company's position against each target
checkpoint, and computes the date after which the gap can no longer be hired
away.

Status: working v0.1, built 2026-10-12. 49 tests, hermetic — the gate is
verified on constructed evidence and a stubbed client, so CI needs no API key.

> **Read this first.** The target schedule, headcount threshold and penalty
> figures in `config.py` are **illustrative defaults reconstructed to
> exercise the arithmetic**. They are not the current framework and this is
> not legal advice. The UAE's Emiratisation rules have been revised more than
> once. Verify every figure against current MOHRE / Nafis rules before
> relying on a projection. The tool prints that warning on every run.

---

## The daily operational problem

Private companies above a headcount threshold carry a mandated Emiratisation
quota: a percentage of skilled roles held by UAE nationals, **rising on a
schedule**, with penalties accruing per unfilled position per month.

The operational failure isn't non-compliance by choice. It's arithmetic
discovered too late. A company checks its ratio in Q4, finds it short by four
positions, and learns the thing everyone learns: **you cannot hire four
skilled Emirati professionals in three weeks.**

Three things keep the miss invisible until it's too late:

- **The target moves.** Hitting this year's ratio says nothing about next
  year's, against a higher bar.
- **The denominator moves.** Every non-Emirati skilled hire raises the number
  of Emirati hires required — so growth quietly increases the obligation, and
  a company hiring nationals *and* growing can still fall behind.
- **Attrition is invisible in the ratio.** One resignation flips compliant to
  non-compliant overnight.

## What the tool computes

Not a compliance percentage. **A date and a number:**

> *You breach on 2026-12-31. You are four roles short. At your 77-day
> time-to-hire, requisitions had to open by 2026-10-15 — which was 17 days
> ago. This year can no longer be fixed by hiring.*

That last clause is the product, and it has its own state:

| State | Meaning |
|---|---|
| `COMPLIANT` | Committed headcount meets the target with headroom |
| `AT_RISK` | Meets it **only** if every open requisition lands, or sits exactly on target |
| `BREACH_AVOIDABLE` | Short, but the hiring runway is still open |
| `BREACH_LOCKED` | Short, and the runway has closed — a budgeting conversation, not a recruitment one |
| `NOT_APPLICABLE` | Below the headcount threshold |
| `INSUFFICIENT_DATA` | Missing a count or a date — **not** a breach |

## Three asymmetries, on purpose

This system's failure mode is **false comfort**, not a wrong number. So the
arithmetic leans one way:

**Compliance is decided on accepted offers only.** A plan that works when
every offer lands and nobody resigns is not a plan. The full pipeline is
projected too, but only to separate `AT_RISK` from `BREACH`. Exits count at
*every* confidence level, including unconfirmed — a resignation is a hole,
not a plan that might not land.

**A year with no published target returns `None`, never zero.** Assuming zero
would report every company as comfortably compliant.

**A missing headcount is unprojectable, never zero.** Zero Emirati staff is a
breach; an unreadable figure is an unknown. A CI assertion checks that an
unprojectable company is never reported in breach.

## The gate — and an honest word about it

Three checks:

- `check_citations()` — a requisition reference that doesn't exist.
- `check_reassurance()` — **the one this system is built around.** Reassuring
  language aimed at a company the engine computed as in breach.
- `check_figures()` — a date or figure nothing computed.

**The reassurance check is a keyword test, and it is evadable.** A test named
`test_the_keyword_check_is_evadable_by_construction` asserts exactly that,
because a limitation documented in a test stays documented.

The real guarantee is architectural: **`report.py` prints the engine's
computed state as the headline for every company, above any drafted text**,
and carries it in its own CSV column. Agent prose is commentary on a verdict
the reader has already seen. The CI guard asserts that column exists, because
a refactor that dropped it would remove the protection while every gate test
still passed.

Full reasoning: [docs/the-assurance-gate.md](docs/the-assurance-gate.md).

## Run it

```bash
make test
make demo-deterministic   # no API key: projections, runway, exposure
make demo                 # full pass; needs ANTHROPIC_API_KEY
```

```bash
ufuq roster.csv --pipeline pipeline.csv --out projections.csv
```

| flag | why |
|---|---|
| `--today YYYY-MM-DD` | pin the run date — every runway counts from it |
| `--company CO-1001` | project one company only |
| `--config FILE` | override targets, penalties and time-to-hire |
| `--no-agents` | computed projection only; no model calls |
| `--fail-on breach\|locked\|held` | exit non-zero, for a scheduled run |

## What the demo shows

Six companies, run against 2026-11-01:

```
  !! BREACH (LOCKED)    CO-1002    Arabian Facilities Co
        2026  target  8.0%  need 15  have  9   gap 6 committed / 4 if all land   -17d runway
              - 4 role(s) short with the hiring runway closed 17 day(s) ago -- at a
                77-day time-to-hire, a requisition opened today cannot land before 2026-12-31
              - exposure if unfilled: 36,000.00 AED (4 role(s) x 1 month(s))

  1 breach_locked   3 breach_avoidable   1 not_applicable   1 insufficient_data
  total exposure if every gap goes unfilled: 7,974,000.00 AED
  1 company(ies) can no longer reach this year's target by hiring -- that is a
  budgeting conversation, not a recruitment one
```

Four things in that output are why the tool exists:

- **`CO-1001` is compliant this year and in breach next year.** Its 2026
  position is fine; its 2027 position is not, because the target rises and
  the denominator grew. Checking only the current year finds nothing wrong.
- **The gap is printed twice, labelled.** `6 committed / 4 if all land` — one
  unlabelled number next to a reason quoting the other is how a reader
  concludes the tool contradicts itself.
- **`BREACH_LOCKED` names the conversation.** The runway closed 17 days ago,
  so this is a budgeting decision. Telling an HR director to "accelerate
  hiring" here would be actively misleading.
- **`CO-1006` is `INSUFFICIENT_DATA`, not a breach.** Its headcount is
  unreadable. Reporting it as zero would manufacture a breach that doesn't
  exist.

## Limits

- **The framework figures are illustrative.** Stated at the top, printed on
  every run, and the single largest real-world risk in this system — larger
  than in the other two, because the rules have genuinely changed more than
  once.
- **Time-to-hire must be the firm's own.** A market average produces a
  last-safe-date that is wrong for this company, which is worse than no date
  because it will be trusted.
- **The gate does not check that a plan is big enough.** A draft proposing
  three hires against a computed gap of five passes every mechanical check.
  The reviewer is told to catch it; the gate does not verify it. This is the
  most worthwhile thing to add next and is tractable.
- **`released` means "recommended by this tool," not "decided."** Nothing
  here files anything or commits a budget.

## Layout

```
src/ufuq/
  rules.py       ALL arithmetic: the double projection, runway, exposure, states
  agents.py      explainer, plan drafter, reviewer, and the Assurance Gate
  config.py      targets, threshold, penalty, time-to-hire -- all on a verify list
  roster.py      snapshot and pipeline loading; a missing count is never a zero
  report.py      terminal view + CSV -- prints the engine's verdict first, by design
  cli.py
examples/        6 companies: a locked breach, a this-year-fine/next-year-short
                 case, a below-threshold company, and one unprojectable row
docs/            the assurance-gate argument, including what it does not catch
tests/           projection arithmetic, gate logic, and an end-to-end CI guard
```
