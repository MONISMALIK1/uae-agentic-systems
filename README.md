# UAE Agentic Systems

Agentic AI systems for UAE operational problems. Each one follows the same
architecture, because the architecture is the point:

> **A deterministic core computes every figure a person acts on. Agents may
> explain, draft and recommend against those figures — never produce one. A
> gate then checks the drafted text against the computed evidence directly,
> and can only ever fail safe in one direction.**

That shape exists for a specific reason rather than an ideological one. In
every domain here, the output is a document a professional acts on — a customs
amendment, an insurance appeal, a filing instruction. **The failure mode is
always fluency.** An invented figure is the right shape, in the right units, in
the right sentence, next to two correct ones. There is no surface signal
separating a computed number from a generated one, and the person reading it
is the person who files it.

So no system here asks a model whether it stayed inside the evidence. Each one
checks.

## Systems

| System | Problem | The gate holds when the model… |
|---|---|---|
| [**masar**](masar/) — *path* | Construction approvals in Dubai are a dependency graph nobody has written down. Submitting out of sequence costs a full authority cycle, and the mistake is discovered weeks later. | …cites a permit number the project doesn't carry, states a date nothing computed, or urges filing an approval the engine marked unfilable |
| [**athar**](athar/) — *trace* | A traffic fine attaches to a plate, not a driver. For fleets where the vehicle changes hands, attribution is a temporal join — and the output is an accusation that leads to a card charge or a wage conversation. | …names a driver the engine could not establish, cites an identifier not in the run, or states a figure nothing computed |

*More systems are added here over time; each is self-contained and runs on its
own.*

## The house pattern

Every system in this repository shares these properties, and departures are
treated as bugs:

- **The deterministic core owns every number.** Scores, dates, classifications
  and thresholds are computed in plain Python, in one file, and nowhere else.
- **Agents are given evidence, not questions.** They receive citable
  identifiers and computed figures, and are asked to write the account — never
  to decide the verdict.
- **The gate checks the text, not the model's self-report.** It extracts every
  identifier and figure from the draft and validates each against the source
  evidence directly.
- **The gate fails safe in exactly one direction.** It can always escalate,
  hold or reopen. It has no code path that clears something a reviewer didn't
  already recommend clearing, and no path back from held.
- **Hard stops never reach a model.** Cases that are unanswerable on their face
  are resolved deterministically before any API call, because there is nothing
  for an agent to add.
- **Unknown is never treated as satisfied.** Absent data, unrecognised statuses
  and unverifiable assertions all resolve toward *not established* — because
  the errors are not symmetric.
- **Tests are hermetic.** Constructed evidence, stubbed clients, no API key, no
  network. The guarantee under test is *"an invented claim is held"*, which
  must not depend on how a model behaves on a given day.
- **The token budget is set correctly from the first commit.** Thinking counts
  against `max_tokens`; a cap tight enough to truncate a reply produces a parse
  error that the gate turns into a hold — so *every* item holds and the run
  reads as the gate working rather than the budget being wrong. That failure
  mode was found once, the expensive way. Every system closes it from day one
  and asserts it in a test.

## Run anything here

```bash
cd <system>
make test                 # hermetic; no API key needed
make demo-deterministic   # the computed core, no model calls
make demo                 # full agentic pass; needs ANTHROPIC_API_KEY
```

## Honest limitations

Every system ships with synthetic fixtures and illustrative thresholds, and
each documents what production calibration would require. **None of them are
regulatory, clinical, legal or tariff advice.** Where a system encodes a rule
from a UAE authority, that rule carries a source pointer and sits on a verify
list the tool prints on every run — because published rules change by circular
and a stale rule produces output that is internally consistent and externally
wrong.

Every system stops at a recommendation. Nothing here files, transmits or
submits anything to any authority, payer or counterparty.

## Contact

Monis Malik — Dubai, UAE
