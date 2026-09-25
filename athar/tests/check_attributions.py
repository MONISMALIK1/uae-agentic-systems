"""CI guard: the attribution gate must hold through the real CLI.

The unit tests exercise `rules` and `agents.gate()` directly. This asserts
the same guarantees end to end, against the shipped fixture, and pins the one
property that must never quietly change:

    NO CONTESTED, COMPANY OR UNATTRIBUTABLE ROW CARRIES A DRIVER.

Everything else here is supporting: fixture states, exposure arithmetic, data
gaps, exit codes, and a probe asserting the gate rejects a name the engine
declined to assert.

No API key: everything runs on the deterministic path, so CI cannot drift
with model behaviour.
"""

import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date  # noqa: E402

from athar import cli  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FINES = os.path.join(ROOT, "examples", "fines.csv")
ASSIGNMENTS = os.path.join(ROOT, "examples", "assignments.csv")
TODAY = "2026-09-22"

# fine_id -> state the fixture was built to produce.
MUST_STATE = {
    "FN-00001": "ATTRIBUTED",      # clean interior hit
    "FN-00002": "COMPANY",         # off-hire at the time
    "FN-00005": "ATTRIBUTED",      # employee shift
    "FN-00008": "CONTESTED",       # inside the handover buffer
    "FN-00009": "COMPANY",         # and its window has closed
    "FN-00010": "UNATTRIBUTABLE",  # no usable timestamp
    "FN-00011": "CONTESTED",       # overlapping custody records
}

MUST_FLAG = {"FN-00010", "H10203"}


def check_cli(out):
    failures = []
    rc = cli.main([FINES, "--assignments", ASSIGNMENTS, "--no-agents",
                   "--no-colour", "--today", TODAY, "--show-all", "-o", out])
    if rc != 0:
        return [f"CLI exited {rc} on the fixture"]

    with open(out, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    by_id = {r["fine_id"]: r for r in rows}

    for fine_id, state in MUST_STATE.items():
        row = by_id.get(fine_id)
        if row is None:
            failures.append(f"{fine_id} missing from the output")
        elif row["state"] != state:
            failures.append(f"{fine_id} is '{row['state']}', expected '{state}'")

    # THE invariant. Nothing the engine could not establish may carry a name.
    for r in rows:
        if r["state"] in ("CONTESTED", "COMPANY", "UNATTRIBUTABLE"):
            if r["driver_id"] or r["driver_name"]:
                failures.append(
                    f"{r['fine_id']} is {r['state']} but names "
                    f"'{r['driver_id'] or r['driver_name']}' -- the engine "
                    f"must never name someone it could not establish")
        if r["state"] == "ATTRIBUTED" and not r["driver_id"]:
            failures.append(f"{r['fine_id']} is ATTRIBUTED with no driver")

    # Every row carries a reason.
    for r in rows:
        if not r["reasons"]:
            failures.append(f"{r['fine_id']} has no reason")

    return failures


def check_ledger():
    from athar import agents, assignments, fines, rules
    from athar.config import Config

    failures = []
    today = date(*(int(p) for p in TODAY.split("-")))
    cfg = Config()
    fine_rows = fines.load(FINES)
    asg_rows = assignments.load(ASSIGNMENTS)
    ledger = rules.assess(fine_rows, asg_rows, cfg, today)

    flagged = {ref for ref, _ in ledger.data_gaps}
    for ref in MUST_FLAG - flagged:
        failures.append(f"{ref} is no longer flagged as a data gap")

    if not ledger.by_state("CONTESTED"):
        failures.append("the fixture no longer produces a CONTESTED fine")
    if not ledger.by_state("ATTRIBUTED"):
        failures.append("the fixture no longer produces an ATTRIBUTED fine")

    rec, contested, company = ledger.exposure_aed()
    total = sum(a.amount_aed or 0.0 for a in ledger.attributions)
    unrecoverable_attributed = sum(
        a.amount_aed or 0.0 for a in ledger.attributions
        if a.state == "ATTRIBUTED" and not a.recoverable)
    if round(rec + contested + company + unrecoverable_attributed, 2) != round(total, 2):
        failures.append(f"exposure buckets ({rec} + {contested} + {company} + "
                        f"{unrecoverable_attributed}) do not sum to {total}")

    # The gate must reject a name the engine declined to assert.
    task = cli.build_task(ledger, asg_rows)
    if task is None:
        failures.append("the fixture produces nothing actionable")
    else:
        allowed = task["allowed"]
        if not allowed["unnameable"]:
            failures.append("no driver is marked unnameable; the naming check "
                            "would be vacuous on this fixture")
        probe = dict(task)
        probe["recommendation"] = "release"
        probe["notice"] = ("Charge " + sorted(allowed["unnameable"])[0]
                           + " for the outstanding fine.")
        probe["explanation"] = probe["rationale"] = ""
        agents.gate(probe, allowed)
        if probe["status"] != "held":
            failures.append("a draft naming an unattributed driver passed the gate")

    return failures


def check_fail_on(out):
    failures = []
    base = [FINES, "--assignments", ASSIGNMENTS, "--no-agents", "--no-colour",
            "--today", TODAY, "-o", out]
    if cli.main(base + ["--fail-on", "contested"]) == 0:
        failures.append("--fail-on contested exited 0 while a fine is contested")
    rc = cli.main(base + ["--fail-on", "none"])
    if rc != 0:
        failures.append(f"--fail-on none exited {rc}; it should never fail")
    return failures


def main():
    out = os.path.join(tempfile.mkdtemp(), "attributions.csv")
    failures = check_cli(out) + check_ledger() + check_fail_on(out)
    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("attribution gate path holds; no contested, company or "
          "unattributable fine names anybody, and fixture states, exposure "
          "arithmetic and exit codes are intact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
