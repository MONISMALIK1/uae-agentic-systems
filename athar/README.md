# athar (أثر) — *trace*

**The fine lands on the plate. The person who earned it is already gone.**
Joins traffic fines to custody records, and refuses to name anybody when the
data cannot settle who was driving.

Status: working v0.1, built 2026-09-25. 50 tests, hermetic — the gate is
verified on constructed evidence and a stubbed client, so CI needs no API key.

---

## The daily operational problem

A traffic fine in the UAE attaches to a vehicle, not a driver. For anyone
running a fleet where the vehicle changes hands — rental companies, leasing
firms, delivery fleets, chauffeur services, corporate pool cars — that single
fact creates a recovery problem with a clock on it.

The lag is what kills you. A fine can surface days or weeks after the event,
arriving through a different channel depending on which emirate issued it,
each with its own format and its own delay profile. By the time a rental
company sees it, the tourist who earned it has flown home, and the only
leverage left is a card deposit they will dispute — successfully, if the
evidence bundle is thin.

For employee fleets the problem inverts but doesn't improve: you know who was
driving, but what may lawfully be deducted from wages is constrained, so an
attribution you cannot *evidence* is one you cannot act on.

## What makes this different from a join

Most of the work is a temporal join — does the violation timestamp fall inside
a custody interval? That part is easy, and it is not the product.

**The product is what happens when the join is ambiguous.** Some fines land in
a handover window; some land where two custody records overlap; some arrive
with a timestamp nobody can parse. A system that resolves those by guessing
produces a cleaner report and a worse business, because each guess is
discovered later, expensively, by the person who was wrongly charged.

So the output has an honest third state:

| State | Meaning | Names a driver? |
|---|---|---|
| `ATTRIBUTED` | One interval covers it, clear of the handover buffer on both sides | **Yes** |
| `CONTESTED` | Handover window, overlapping records — the data cannot settle it | **No** |
| `COMPANY` | No interval covers it; the vehicle was off-hire | No |
| `UNATTRIBUTABLE` | No usable timestamp; it cannot be placed at all | No |

**This system's output is an accusation.** It leads to a card being charged or
a conversation about someone's wages. So it must never make one it cannot
support — and the gate below makes that refusal unforgeable.

## The design

```
fines.csv + assignments.csv
    |
    +-- loose column matching     every fleet system names these differently
    +-- timestamp parsing         an unparseable time is never defaulted to midnight
    |
    +-- rules.py                  ALL logic: the custody join, the handover
    |       |                     buffer, the dispute clock, evidence checks
    |       +-- facts()           citable identifiers + computed figures
    |       |
    |       +--> explainer -> notice drafter -> reviewer  (cite, never name)
    |       |
    |       +--> gate()           the Attribution Gate; runs last, always
    |
  attributions.csv  +  terminal report
```

Three checks, because a recovery notice fails three ways:

- `check_citations()` — an identifier that doesn't exist in this run.
- `check_naming()` — **the one that matters.** A driver identifier attached to
  a fine the engine did not attribute. Those names are *real people in the
  fleet* — which is exactly why naming them is an accusation the data doesn't
  support.
- `check_figures()` — an amount or day count nothing computed.

Naming is checked **before** figures, because it is the more serious failure
by a wide margin.

## Run it

```bash
make test
make demo-deterministic   # no API key: the join, the clock, the evidence check
make demo                 # full pass; needs ANTHROPIC_API_KEY
```

```bash
athar fines.csv --assignments assignments.csv --out attributions.csv
```

| flag | why |
|---|---|
| `--today YYYY-MM-DD` | pin the run date — the dispute clock counts from it |
| `--config FILE` | override windows, the handover buffer and thresholds |
| `--show-all` | list every fine, not only actionable ones |
| `--no-agents` | computed ledger only; no model calls |
| `--fail-on contested\|held` | exit non-zero, for a scheduled run |

## What the demo shows

Twelve fines across seven vehicles, run against 2026-09-22:

```
  CONTESTED  (2)
    ?? CONTESTED  FN-00008   E91002  AED 900.00   -- not established --
                  - the violation falls within 45 minutes of a custody boundary
                    on ASG-00501 -- inside the handover window, where the vehicle
                    may have been with either party or with neither
    ?? CONTESTED  FN-00011   G20044  AED   5.00   -- not established --
                  - custody intervals overlap at the moment of the violation
                    (ASG-00601, ASG-00602) -- the record contradicts itself

  2 contested   6 attributed   3 company   1 unattributable
  recoverable 6,500.00 AED   contested 905.00 AED   company-borne 2,555.00 AED
  the contested figure is the cost of timestamp discipline, not of bad drivers
```

Four things in that output are why the tool exists:

- **The contested column reads `-- not established --`, not a blank.** A blank
  invites someone to fill it in.
- **The contested total is a diagnostic, not a loss.** It measures how sloppy
  the fleet's own handover timestamps are. Tighten those and the number falls.
- **An employee attribution is flagged, not billed.** `FN-00005` is attributed
  to a shift driver — and marked as a conversation constrained by labour law,
  not a deduction this tool can authorise.
- **A fine with an unreadable timestamp is `UNATTRIBUTABLE`, not midnight.**
  Defaulting to midnight would silently place it inside whichever assignment
  spanned that hour — a false attribution created by rounding.

## Documentation

- [docs/the-attribution-gate.md](docs/the-attribution-gate.md) — the safety
  argument: why the output is an accusation, what licenses a name, every path
  to `held`, and what the gate does *not* catch (including one real gap:
  naming someone in prose without an identifier).

## Design notes

**Attribution and recoverability are separate questions.** A fine can be
correctly attributed and still unrecoverable — a rental with no signed
handover document would lose a chargeback. Conflating the two hides *why*
recovery failed, so they are computed and reported separately.

**The handover buffer has one safe direction.** Widening it only ever moves
fines into contested; a test asserts that. It is a firm-specific estimate of
that firm's own timestamp discipline and should be measured, not assumed.

**An unknown dispute window defaults short.** Assuming a generous deadline is
how a contestable fine quietly goes uncontested.

**Priority is independent of who was named.** A contested fine with a closing
window is urgent precisely because the evidence must be found before the
window shuts.

## Limits

- **Windows and buffers are illustrative.** Dispute windows differ by issuing
  authority and change. **Not legal advice** — verify against the authority's
  current rules, and confirm any wage deduction against UAE labour law and the
  employment contract. The report prints the verify list on every run.
- **No portal integration.** Fines arrive as a CSV. In production, getting
  them out of the authorities' human-facing portals is often the hard part.
- **The naming check is identifier-shaped.** It catches a driver ID attached
  to an unattributed fine. It does not catch someone identified in prose
  without an ID — a real gap, documented, which a production version would
  close with a roster name-match.
- **`released` means "recommended by this tool," not "charged."** Nothing here
  charges a card, deducts from wages, or contacts anybody.

## Layout

```
src/athar/
  rules.py         ALL logic: custody join, handover buffer, clock, evidence
  agents.py        explainer, notice drafter, reviewer, and the Attribution Gate
  config.py        windows, buffers and thresholds, with a verify list
  fines.py         fine loading; an unparseable timestamp is never defaulted
  assignments.py   custody records, evidence completeness
  report.py        terminal view + the attribution CSV
  cli.py
examples/          12 fines across 7 vehicles: a handover-window fine,
                   overlapping custody, an off-hire fine, a closed window,
                   and one with an unreadable timestamp
docs/              the attribution-gate safety argument
tests/             join logic, gate logic, and an end-to-end CI guard
```
