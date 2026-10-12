"""CI guard: the assurance path must hold through the real CLI.

Pins the properties that must never quietly change:

  * the computed state appears in its own CSV column, always, for every
    company -- that column is the architectural guarantee behind the
    reassurance check, and a refactor that drops it would silently remove
    the protection
  * a company in breach is never reported compliant
  * the fixture's states stay where it was built to put them
  * an unprojectable company is not a breach, and a below-threshold company
    is not a breach
  * the gate rejects reassurance aimed at a company in breach
  * --fail-on gives a scheduled run a non-zero exit

No API key: everything runs on the deterministic path.
"""

import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date  # noqa: E402

from ufuq import cli  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ROSTER = os.path.join(ROOT, "examples", "roster.csv")
PIPELINE = os.path.join(ROOT, "examples", "pipeline.csv")
TODAY = "2026-11-01"

MUST_STATE = {
    "CO-1001": "BREACH_AVOIDABLE",   # compliant now, short in later years
    "CO-1002": "BREACH_LOCKED",      # short with the runway already closed
    "CO-1004": "NOT_APPLICABLE",     # below the headcount threshold
    "CO-1006": "INSUFFICIENT_DATA",  # missing headcount
}


def check_cli(out):
    failures = []
    rc = cli.main([ROSTER, "--pipeline", PIPELINE, "--no-agents",
                   "--no-colour", "--today", TODAY, "-o", out])
    if rc != 0:
        return [f"CLI exited {rc} on the fixture"]

    with open(out, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    if "computed_state" not in (rows[0].keys() if rows else []):
        failures.append("the computed_state column is gone -- that column is "
                        "the architectural guarantee behind the reassurance "
                        "check, not a presentation detail")

    by_company = {}
    for r in rows:
        by_company.setdefault(r["company_id"], r)

    for company_id, state in MUST_STATE.items():
        row = by_company.get(company_id)
        if row is None:
            failures.append(f"{company_id} missing from the output")
        elif row["computed_state"] != state:
            failures.append(f"{company_id} is '{row['computed_state']}', "
                            f"expected '{state}'")

    # Every row carries the engine's verdict, not only the ones with
    # checkpoints.
    for r in rows:
        if not r["computed_state"]:
            failures.append(f"{r['company_id']} has no computed_state")

    # Nothing may be drafted in a run that made no model calls.
    for r in rows:
        for col in ("explanation", "plan", "advice_status"):
            if r[col]:
                failures.append(f"--no-agents populated '{col}' for "
                                f"{r['company_id']}")
                break

    return failures


def check_portfolio():
    from ufuq import agents, roster, rules
    from ufuq.config import Config

    failures = []
    today = date(*(int(p) for p in TODAY.split("-")))
    cfg = Config()
    snapshots = roster.load_roster(ROSTER)
    events = roster.load_pipeline(PIPELINE)
    portfolio = rules.assess_all(snapshots, events, cfg, today)
    by_id = {p.company_id: p for p in portfolio.projections}

    if not portfolio.by_state("BREACH_LOCKED"):
        failures.append("the fixture no longer produces a BREACH_LOCKED "
                        "company -- the flagship state is unexercised")

    # An unprojectable or below-threshold company must never be a breach.
    for company_id in ("CO-1004", "CO-1006"):
        p = by_id.get(company_id)
        if p and p.in_breach:
            failures.append(f"{company_id} is reported in breach; a missing "
                            f"count or a below-threshold company is not a "
                            f"breach")

    if portfolio.total_exposure() <= 0:
        failures.append("the fixture produces no exposure figure")

    # The gate must reject reassurance aimed at a company in breach.
    for task in cli.build_tasks(portfolio):
        allowed = task["allowed"]
        if not allowed["citations"] and not allowed["numbers"]:
            failures.append(f"{task['company_id']} would reach an agent with "
                            f"no evidence to cite")
        if not allowed["in_breach"]:
            continue
        probe = dict(task)
        probe["recommendation"] = "release"
        probe["explanation"] = "The company is on track; no action is required."
        probe["plan"] = probe["rationale"] = ""
        agents.gate(probe, allowed)
        if probe["status"] != "held":
            failures.append(f"{task['company_id']}: reassurance aimed at a "
                            f"company in breach passed the gate")

    return failures


def check_fail_on(out):
    failures = []
    base = [ROSTER, "--pipeline", PIPELINE, "--no-agents", "--no-colour",
            "--today", TODAY, "-o", out]
    if cli.main(base + ["--fail-on", "breach"]) == 0:
        failures.append("--fail-on breach exited 0 while a company is in breach")
    if cli.main(base + ["--fail-on", "locked"]) == 0:
        failures.append("--fail-on locked exited 0 while a breach is locked")
    rc = cli.main(base + ["--fail-on", "none"])
    if rc != 0:
        failures.append(f"--fail-on none exited {rc}; it should never fail")
    return failures


def main():
    out = os.path.join(tempfile.mkdtemp(), "projections.csv")
    failures = check_cli(out) + check_portfolio() + check_fail_on(out)
    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("assurance path holds; the computed state is carried in its own "
          "column, no unprojectable company is reported in breach, and "
          "reassurance aimed at a breach is rejected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
