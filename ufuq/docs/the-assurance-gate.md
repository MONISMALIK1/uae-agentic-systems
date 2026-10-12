# The Assurance Gate

The safety argument for this system. It differs from the other two in this
repository in one important way, and the difference is worth stating first:

> **The gate here is not the primary guarantee. The report layout is.**

That is an unusual thing to admit in a document about a gate, so this file
explains why it is true, and why the gate is still worth having.

---

## The failure this system has

Not a wrong number. **False comfort.**

A company told it is on track does nothing. The shortfall accrues quietly,
month by month, against a deadline that — because hiring takes months —
became arithmetically unreachable long before anyone looked at the number.
By the time the deadline arrives, the only remaining decision is how to
budget for the penalty.

That failure produces no alarm at any point. An error in the pessimistic
direction costs a firm an unnecessary requisition; an error in the reassuring
direction costs them the year. The whole system is tuned around that
asymmetry.

## Three asymmetries in the arithmetic

Before the gate, the engine itself leans one way:

**1. Compliance is decided on committed headcount only.**
Accepted offers count. Offered and sourcing do not. A plan that works when
every offer lands and nobody resigns is not a plan, and reporting it as
compliance is the exact failure above. The pipeline projection is computed
too, but only to distinguish `AT_RISK` ("closes if everything lands") from
`BREACH` ("does not close even then").

Exits are the mirror image: they count at **every** confidence level,
including unconfirmed. A resignation is a hole, not a plan that might not
land, and counting exits only optimistically would flatter the committed
number — the one direction this tool must not err in.

**2. A year with no published target returns `None`, never zero.**
Assuming zero would report every company as comfortably compliant for every
unscheduled year.

**3. A missing headcount is unprojectable, never zero.**
Zero Emirati staff is a breach. An unreadable figure is an unknown. They must
not produce the same report, and a CI assertion checks that an unprojectable
company is never reported in breach.

## The architectural guarantee

`report.py` prints the engine's computed state as the **headline for every
company, above any drafted text**, and writes it to its own `computed_state`
CSV column.

Agent prose is supplementary commentary on a verdict the reader has already
seen. A drafting layer that gets creative can editorialise beneath the
verdict; it cannot overwrite it.

That ordering is a safety property, not a presentation choice, and the CI
guard asserts the column exists — a refactor that quietly dropped it would
remove the protection while every test about the gate still passed.

## The gate, and its honest limitation

`check_reassurance()` holds any draft using reassuring language about a
company whose computed state is `BREACH_LOCKED` or `BREACH_AVOIDABLE`:
*compliant*, *on track*, *no action required*, *meets the target*,
*comfortable*, *well-positioned*, *safe*.

**It is a keyword test, and it is evadable.** A model writing "your position
for this year looks perfectly fine as it stands" passes it. There is a test
named `test_the_keyword_check_is_evadable_by_construction` that asserts
exactly this, because a limitation documented in a test is one that stays
documented.

So why keep it? Because the ordinary phrasings of reassurance are not
adversarial — they are what a helpful assistant reaches for by default when
summarising. The filter catches the common case cheaply, and the report
layout catches the rest. Defence in depth, with the weaker layer labelled as
the weaker layer.

One subtlety worth noting: the pattern deliberately does **not** fire on
"compliance gap", "compliance shortfall", "compliance risk" or "compliance
breach". Without that exclusion the gate would hold every accurate
description of a breach, which would make it useless and would train whoever
maintains it to switch it off.

## Every path to `held`

1. Any agent failing — exception, refusal, parse error.
2. A truncated reply (`stop_reason == "max_tokens"`, checked explicitly).
3. A requisition reference that does not exist.
4. **Reassuring language aimed at a company in breach.**
5. A date or figure no computation produced.
6. The reviewer recommending `hold`.

Reassurance is checked **before** figures, because it is the failure that
produces no alarm. A test asserts that ordering.

> **The gate can only move toward `held`.** No branch releases advice the
> reviewer did not recommend releasing, and no path back from held.

## What the gate does not catch

- **Reassurance written around the keywords.** Stated above; mitigated by the
  report layout, not closed.
- **An understated plan.** A draft proposing three hires against a computed
  gap of five would pass every mechanical check. The system prompt forbids
  it and the reviewer is told to catch it, but the gate does not verify it.
  This is the most worthwhile thing to add next, and it is tractable:
  extracting a proposed headcount and comparing it to `committed_gap` is the
  same shape as the checks already here.
- **Whether the target schedule is right.** If `config.py` carries the wrong
  percentages, every projection is internally consistent and externally
  wrong. This is the largest real-world risk in the system — larger than in
  the other two — because the framework has been revised more than once. Every
  figure carries a source pointer, sits on a verify list, and the report
  prints that list on every run.
- **Whether the firm's time-to-hire is real.** The last-safe-requisition date
  is only as good as that input, and a market average produces a date that is
  wrong for this specific company — which is worse than no date, because it
  will be trusted.

## The failure mode that looks exactly like the gate working

Thinking is on by default on the configured model, and `max_tokens` caps
thinking and response text together. A cap tight enough to truncate the JSON
produces a parse error, which the gate turns into a hold — so *every* company
holds, and the run reads as the gate working rather than the budget being
wrong.

`MAX_TOKENS = 16000`, `stop_reason == "max_tokens"` is raised as itself, and
a test asserts both the floor and that the value reaches every request.

## Why the tests are hermetic

Constructed evidence, stubbed client, no API key, no network. The guarantee
under test is *"a company in breach is never told it is fine"*, which must
not depend on how a model behaves on a given day.
