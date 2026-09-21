"""CI guard: the sequencing gate must hold through the real CLI.

The unit tests exercise `rules` and `agents.gate()` directly. This asserts
the same guarantees end to end, against the shipped fixture, on the code path
a user actually runs -- and pins the things that must never quietly change:

  * a submission filed out of sequence is flagged WILL_BOUNCE
  * --no-agents leaves every drafted column empty, so nothing written by a
    model can appear in a run that made no model calls
  * the fixture's verdicts and critical paths stay where it was built to put
    them
  * an unrecognised status never unblocks a downstream filing
  * every task the CLI would hand to an agent carries real evidence, and the
    gate rejects an invented date on every one of them
  * --fail-on gives a scheduled run a non-zero exit

No API key: everything here runs on the deterministic path, so CI cannot
drift with model behaviour.
"""

import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date  # noqa: E402

from masar import cli  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PROJECTS = os.path.join(ROOT, "examples", "projects.csv")
TODAY = "2026-09-21"

# (project, approval) -> verdict it must carry.
MUST_VERDICT = {
    ("PRJ-001", "BUILDING_PERMIT"): "WILL_BOUNCE",  # filed before DEWA_NOC cleared
    ("PRJ-001", "DEWA_NOC"): "FILED",
    ("PRJ-001", "CONCEPT"): "GRANTED",
    ("PRJ-002", "BUILDING_PERMIT"): "BLOCKED",      # prereqs clear, doc missing
    ("PRJ-003", "CONCEPT"): "FILED",
    ("PRJ-003", "DCD_DESIGN"): "BLOCKED",
    ("PRJ-004", "DEWA_NOC"): "BLOCKED",
}

# Projects whose critical path must terminate at COMPLETION.
MUST_HAVE_PATH = {"PRJ-001", "PRJ-002", "PRJ-003", "PRJ-004"}


def check_cli(out):
    failures = []
    rc = cli.main([PROJECTS, "--no-agents", "--no-colour", "--today", TODAY,
                   "-o", out])
    if rc != 0:
        return [f"CLI exited {rc} on the fixture"]

    with open(out, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    by_key = {(r["project_id"], r["approval_code"]): r for r in rows}

    for key, verdict in MUST_VERDICT.items():
        row = by_key.get(key)
        if row is None:
            failures.append(f"{key} missing from the output")
        elif row["verdict"] != verdict:
            failures.append(f"{key} is '{row['verdict']}', expected '{verdict}'")

    # Nothing may be drafted in a run that made no model calls.
    for r in rows:
        for col in ("recommendation", "explanation", "actions", "rationale"):
            if r[col]:
                failures.append(f"--no-agents populated '{col}' for "
                                f"{r['project_id']}/{r['approval_code']}")
                break

    # Every row carries a verdict and a reason.
    for r in rows:
        if not r["verdict"]:
            failures.append(f"{r['project_id']}/{r['approval_code']} has no verdict")
        if not r["reasons"]:
            failures.append(f"{r['project_id']}/{r['approval_code']} has no reason")

    return failures


def check_assessments():
    from masar import agents, projects, rules
    from masar.config import Config

    failures = []
    today = date(*(int(p) for p in TODAY.split("-")))
    cfg = Config()
    loaded = projects.load(PROJECTS)
    assessments = [rules.assess(p, cfg, today) for p in loaded]
    by_id = {a.project_id: a for a in assessments}

    for pid in MUST_HAVE_PATH:
        a = by_id.get(pid)
        if not a:
            failures.append(f"{pid} missing from the assessment")
            continue
        if not a.critical_path:
            failures.append(f"{pid} has no critical path")
        elif a.critical_path[-1] != "COMPLETION":
            failures.append(f"{pid} critical path ends at "
                            f"'{a.critical_path[-1]}', expected COMPLETION")
        if len(a.critical_path) != len(set(a.critical_path)):
            failures.append(f"{pid} critical path revisits a node")
        if not a.forecast_completion:
            failures.append(f"{pid} has no forecast completion date")

    # The fail-safe: an unrecognised status must be reported, never trusted.
    prj4 = by_id.get("PRJ-004")
    if prj4 and not any("unrecognised" in g for g in prj4.data_gaps):
        failures.append("PRJ-004's unrecognised status is no longer reported")
    if prj4 and not any("not in the configured approval graph" in g
                        for g in prj4.data_gaps):
        failures.append("PRJ-004's unknown approval code is no longer reported")

    if not any(a.will_bounce() for a in assessments):
        failures.append("the fixture no longer produces a WILL_BOUNCE")

    # Every task the CLI would send to an agent must carry real evidence, and
    # the gate must reject an invented date on every one of them.
    for task in cli.build_tasks(assessments):
        allowed = task["allowed"]
        if not allowed["references"] and not allowed["dates"]:
            failures.append(f"{task['project_id']} would reach an agent with "
                            f"no evidence to cite")
        probe = dict(task)
        probe["recommendation"] = "release"
        probe["actions"] = "Expect clearance by 2031-12-31."
        probe["explanation"] = probe["rationale"] = ""
        agents.gate(probe, allowed)
        if probe["status"] != "held":
            failures.append(f"{task['project_id']}: an invented date passed "
                            f"the gate")

    return failures


def check_fail_on(out):
    failures = []
    base = [PROJECTS, "--no-agents", "--no-colour", "--today", TODAY, "-o", out]
    if cli.main(base + ["--fail-on", "will-bounce"]) == 0:
        failures.append("--fail-on will-bounce exited 0 while a submission "
                        "is queued to bounce")
    rc = cli.main(base + ["--fail-on", "none"])
    if rc != 0:
        failures.append(f"--fail-on none exited {rc}; it should never fail")
    return failures


def main():
    out = os.path.join(tempfile.mkdtemp(), "schedule.csv")
    failures = check_cli(out) + check_assessments() + check_fail_on(out)
    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("sequencing gate path holds; fixture verdicts, critical paths, "
          "fail-safe statuses and exit codes are intact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
