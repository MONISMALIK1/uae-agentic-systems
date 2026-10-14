"""CI guard: the claim path must hold through the real CLI.

Pins the property that must never quietly change:

    A UNIT WITH INSUFFICIENT EVIDENCE CARRIES NO CLAIM FIGURE, and never
    reaches an agent at all.

Plus: fixture states, the ceiling being the sum of only claimable units, data
gaps, and a probe asserting the gate rejects a claim above the ceiling.
"""

import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date  # noqa: E402

from mizan import cli  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
UNITS = os.path.join(ROOT, "examples", "units.csv")
READINGS = os.path.join(ROOT, "examples", "readings.csv")
TODAY = "2026-12-01"

MUST_STATE = {
    "UNT-0101": "OVER_ALLOCATED",
    "UNT-0102": "WITHIN_TOLERANCE",
    "UNT-0103": "UNDER_ALLOCATED",
    "UNT-0104": "INSUFFICIENT_EVIDENCE",
    "UNT-0301": "NOT_ASSESSABLE",
}


def check_cli(out):
    failures = []
    rc = cli.main([UNITS, "--readings", READINGS, "--no-agents", "--no-colour",
                   "--today", TODAY, "-o", out])
    if rc != 0:
        return [f"CLI exited {rc} on the fixture"]

    with open(out, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    by_id = {r["unit_id"]: r for r in rows}

    for unit_id, state in MUST_STATE.items():
        row = by_id.get(unit_id)
        if row is None:
            failures.append(f"{unit_id} missing from the output")
        elif row["state"] != state:
            failures.append(f"{unit_id} is '{row['state']}', expected '{state}'")

    # THE invariant: nothing without a finding carries a claim figure.
    for r in rows:
        if r["state"] in ("INSUFFICIENT_EVIDENCE", "NOT_ASSESSABLE"):
            if float(r["recoverable_ceiling_aed"] or 0) != 0:
                failures.append(
                    f"{r['unit_id']} is {r['state']} but carries a ceiling of "
                    f"{r['recoverable_ceiling_aed']} -- a unit with no finding "
                    f"must carry no claim figure")
        if r["state"] == "UNDER_ALLOCATED" and float(r["recoverable_ceiling_aed"] or 0) != 0:
            failures.append(f"{r['unit_id']} is under-allocated but carries a "
                            f"recovery figure")
        if not r["reasons"]:
            failures.append(f"{r['unit_id']} has no reason")

    return failures


def check_portfolio():
    from mizan import agents, rules, units
    from mizan.config import Config

    failures = []
    today = date(*(int(p) for p in TODAY.split("-")))
    cfg = Config()
    pf = rules.assess(units.load_units(UNITS), units.load_readings(READINGS),
                      cfg, today)

    for state in ("OVER_ALLOCATED", "UNDER_ALLOCATED", "WITHIN_TOLERANCE",
                  "INSUFFICIENT_EVIDENCE", "NOT_ASSESSABLE"):
        if not pf.by_state(state):
            failures.append(f"the fixture no longer exercises {state}")

    expected = round(sum(f.recoverable_ceiling_aed for f in pf.claimable()), 2)
    if pf.total_ceiling_aed() != expected:
        failures.append("the portfolio ceiling is not the sum of claimable units")

    if not any("not on the allocation schedule" in n for _, n in pf.data_gaps):
        failures.append("the orphan reading is no longer surfaced")

    task = cli.build_task(pf)
    if task is None:
        failures.append("the fixture produces nothing claimable")
        return failures

    allowed = task["allowed"]

    # A blocked unit must never be offered to an agent.
    offered = {u["unit_id"] for u in task["facts"]["units"]}
    for f in pf.by_state("INSUFFICIENT_EVIDENCE"):
        if f.unit_id in offered:
            failures.append(f"{f.unit_id} has no finding but was offered to "
                            f"an agent")
        if f.unit_id not in allowed["blocked_units"]:
            failures.append(f"{f.unit_id} is not in the blocked set, so claim "
                            f"language about it would pass the gate")

    # The gate must reject a claim above the ceiling.
    probe = dict(task)
    probe["recommendation"] = "release"
    probe["claim"] = f"We seek recovery of {allowed['ceiling'] + 100000:,.2f} AED."
    probe["explanation"] = probe["rationale"] = ""
    agents.gate(probe, allowed)
    if probe["status"] != "held":
        failures.append("a claim above the computed ceiling passed the gate")

    return failures


def check_fail_on(out):
    failures = []
    base = [UNITS, "--readings", READINGS, "--no-agents", "--no-colour",
            "--today", TODAY, "-o", out]
    if cli.main(base + ["--fail-on", "over-allocated"]) == 0:
        failures.append("--fail-on over-allocated exited 0 while a unit is over-allocated")
    if cli.main(base + ["--fail-on", "under-allocated"]) == 0:
        failures.append("--fail-on under-allocated exited 0 while a unit is under-allocated")
    if cli.main(base + ["--fail-on", "none"]) != 0:
        failures.append("--fail-on none should never fail")
    return failures


def main():
    out = os.path.join(tempfile.mkdtemp(), "review.csv")
    failures = check_cli(out) + check_portfolio() + check_fail_on(out)
    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("claim path holds; no unit without a finding carries a claim figure "
          "or reaches an agent, and a claim above the ceiling is rejected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
