# masar (مسار) — *path*

**The critical path through Dubai's approval maze.** Reads a project's
approval state, walks the authority dependency graph, and tells a planning
engineer which submission they are about to file that will bounce — before
they file it.

Status: working v0.1, built 2026-09-21. 38 tests, hermetic — the gate is
verified on constructed evidence and a stubbed client, so CI needs no API key.

---

## The daily operational problem

A building in Dubai doesn't get one permit. It gets a *sequence* of them, from
authorities that don't talk to each other: the building-permit authority
(Dubai Municipality, Trakhees, DDA or Dubai South, depending on which square
kilometre the plot sits in); DEWA for the load NOC and later energisation;
Civil Defence for fire-and-life-safety design approval, then site inspection;
RTA if anything touches a road; telecom infrastructure; sewerage; then the
completion certificate that finally makes the asset rentable.

Each has its own portal, document set and cycle time — and its own
**prerequisites**. The failure mode isn't rejection on merit. It's submitting
for approval X before approval Y has landed, getting bounced on a technicality,
and rejoining a multi-week queue.

**The asymmetry that makes this a tool:** a delay is discovered weeks after the
mistake that caused it. By the time the rejection email arrives, the sequencing
error is a month old and the cycle is gone.

The dependency map lives in the head of one senior planning engineer per firm,
who is also the bottleneck, and who eventually leaves.

## The design

```
projects.csv
    |
    +-- loose column matching     every firm tracks these differently
    +-- status parsing            an unrecognised status never unblocks a filing
    |
    +-- rules.py                  ALL graph logic: prerequisites, readiness,
    |       |                     critical path, every forecast date
    |       +-- facts()           citable references + computed dates
    |       |
    |       +--> explainer -> action drafter -> reviewer  (cite, never compute)
    |       |
    |       +--> gate()           the Sequencing Gate; runs last, always
    |
  schedule.csv  +  terminal report
```

**The Sequencing Gate is the product.** Every verdict and date comes from
`rules.py`. Agents may explain, draft and recommend against them — they may
not introduce a reference they weren't handed, state a date nothing computed,
or urge filing something the engine marked unfilable.

Three checks, because sequencing advice fails three ways:

- `check_references()` — a permit number nobody can produce.
- `check_dates()` — **the one that actually gets acted on.** A wrong date
  doesn't look wrong; it looks like a date, and it's found out a month later.
- `check_verdict()` — the engine owns readiness. A draft urging *"submit
  BUILDING_PERMIT now"* when the engine says `WILL_BOUNCE` is held.

## Run it

```bash
make test
make demo-deterministic   # no API key: verdicts, critical path, forecast dates
make demo                 # full pass; needs ANTHROPIC_API_KEY
```

```bash
masar projects.csv --out schedule.csv
```

| flag | why |
|---|---|
| `--today YYYY-MM-DD` | pin the run date — every forecast counts from it |
| `--project PRJ-001` | assess one project only |
| `--config FILE` | override the approval graph and cycle times; unknown keys rejected |
| `--show-granted` | list already-granted approvals too |
| `--no-agents` | computed schedule only; no model calls |
| `--fail-on will-bounce\|held` | exit non-zero, for a scheduled run |

## What the demo shows

Four projects across three jurisdictions, run against 2026-09-21:

```
  PRJ-001  Marina Tower C  [dubai_municipality]
    forecast completion 2026-12-03
    critical path: DEWA_NOC -> BUILDING_PERMIT -> DCD_SITE -> DEWA_ENERGISE -> COMPLETION

    !! WILL BOUNCE * BUILDING_PERMIT   file from --
                     - filed 2026-07-02 but 1 prerequisite(s) are not granted: DEWA_NOC
                     - the authority will reject on sequence, and the cycle already spent is lost
```

Four things in that output are why the tool exists:

- **The building permit was filed eleven weeks ago and is going to be
  rejected.** Not because anything is wrong with it — because DEWA_NOC hadn't
  cleared when it went in. Nobody at the firm knows yet.
- **The critical path names the one approval setting the schedule.**
  `DEWA_NOC` is what everything else is waiting behind; the other four NOCs
  feeding the permit are irrelevant to the date.
- **An unrecognised status never unblocks a filing.** `PRJ-004` has a row
  marked `approved` — not a status this tool recognises. It's reported as a
  data gap and treated as *not granted*, because guessing the other way sends
  a submission to an authority that will bounce it.
- **Forecast dates carry contingency.** A cycle time quoted raw gets treated
  as a promise; every forecast is padded and the padding is configurable.

## Documentation

- [docs/the-sequencing-gate.md](docs/the-sequencing-gate.md) — the safety
  argument: what licenses a reference, a date and a verdict; every path to
  `held`; what the gate does *not* catch; and the token-budget failure mode
  that looks exactly like the gate working.

## Design notes

**All graph logic lives in one file.** `rules.py` computes prerequisites,
readiness, critical path and every date. A model is never asked to decide
whether a submission is ready. An invented date in sequencing advice is not
obviously wrong to the engineer reading it, and it's wrong at the point where
a concrete pour has been planned against it.

**Unknown is never treated as satisfied.** An absent approval row, an
unrecognised status, or a `granted` row with no grant date all mean *not
granted*. Guessing that an unlisted prerequisite is met costs a full authority
cycle; guessing the other way costs someone checking a document they already
have. The errors aren't symmetric, so the defaults aren't either.

**The gate can only hold, never release.** No path from `held` back to
`released`, and no branch that releases advice the reviewer didn't recommend
releasing.

**The token budget is set correctly from the first commit.** A `max_tokens`
cap tight enough to truncate a reply produces a parse error the gate turns
into a hold — every project would hold, and the run would read as the gate
working rather than the budget being wrong.

## Limits

- **The dependency graph is an illustrative reconstruction.** It is *not*
  regulatory advice. Authority requirements change by circular, cycle times
  drift, and the jurisdictional map is redrawn when a new zone is created.
  **Verify every entry against the authority's current published requirements
  before filing or deferring anything.** This is the biggest real-world risk
  in the system, and the report prints the verify list on every run.
- **No portal integration.** Status arrives as a CSV. In production, getting
  live authority status into that CSV is often the hard part, and this
  repository does not solve it.
- **Cycle times are planning figures, not promises.** They are averages with
  a configurable contingency, not commitments from any authority.
- **The gate is reference-shaped and date-shaped.** It catches an invented
  permit number and an invented date. It does not catch a true reference
  attached to a false characterisation, and it does not catch omission.
- **`released` means "recommended by this tool," not "filed."** A planning
  engineer is the sole authority, every time.

## Layout

```
src/masar/
  rules.py        ALL graph logic: prerequisites, readiness, critical path, dates
  agents.py       explainer, action drafter, reviewer, and the Sequencing Gate
  config.py       the approval graph and cycle times, with a verify list
  projects.py     project state loading, loose columns, fail-safe statuses
  report.py       terminal view + the schedule CSV
  cli.py
examples/         4-project fixture across 3 jurisdictions: a bouncing
                  submission, a document-blocked permit, an unrecognised
                  status and an unknown approval code
docs/             the sequencing-gate safety argument
tests/            graph logic, gate logic, and an end-to-end CI guard
```
