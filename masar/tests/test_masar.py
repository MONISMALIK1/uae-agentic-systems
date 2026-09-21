"""The graph logic: prerequisites, readiness, critical path, forecast dates.

Everything here runs on constructed rows -- no CSV, no network, no model.
If one of these moves, a submission a planning engineer would have filed has
moved with it, or one they would not have has appeared.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date  # noqa: E402

from masar import projects, rules  # noqa: E402
from masar.config import Config  # noqa: E402

TODAY = date(2026, 9, 21)


def _state(code, status="granted", granted=TODAY, filed=None, docs=None, ref=""):
    return projects.ApprovalState(
        project_id="PRJ-001", approval_code=code, status=status,
        filed_on=filed, granted_on=granted if status == "granted" else None,
        documents_held=list(docs or []), reference=ref)


def _project(states=None, jurisdiction="dubai_municipality"):
    p = projects.Project(project_id="PRJ-001", project_name="Test Tower",
                         jurisdiction=jurisdiction)
    for s in (states or []):
        p.states[s.approval_code] = s
    return p


def _all_granted_through(codes, docs_for=None):
    """Every code granted, with documents attached where asked."""
    docs_for = docs_for or {}
    return [_state(c, docs=docs_for.get(c)) for c in codes]


def _verdict(assessment, code):
    for r in assessment.readiness:
        if r.approval_code == code:
            return r.verdict
    raise AssertionError(f"{code} not in assessment")


def _readiness(assessment, code):
    for r in assessment.readiness:
        if r.approval_code == code:
            return r
    raise AssertionError(f"{code} not in assessment")


# --- the fail-safe asymmetry -------------------------------------------------

def test_an_absent_approval_is_not_granted():
    """A project with no row for an approval has not obtained it."""
    p = _project()
    assert p.state("AFF").is_granted is False


def test_granted_without_a_date_is_not_granted():
    """A row asserting 'granted' with no date is an assertion nobody can
    check, and an unverifiable assertion must not unblock a filing."""
    s = projects.ApprovalState("PRJ-001", "AFF", status="granted", granted_on=None)
    assert s.is_granted is False


def test_an_unrecognised_status_never_unblocks(tmp_path=None):
    path = os.path.join(tempfile.mkdtemp(), "p.csv")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("project_id,approval_code,status,granted_on\n"
                 "PRJ-001,AFF,approved,2026-05-08\n")
    [p] = projects.load(path)
    assert p.state("AFF").is_granted is False
    assert any("unrecognised" in n for n in p.state("AFF").parse_notes)


# --- readiness ---------------------------------------------------------------

def test_first_approval_with_documents_is_ready():
    p = _project()
    p.states["AFF"] = _state("AFF", status="not_started", granted=None,
                             docs=["title_deed", "site_plan"])
    a = rules.assess(p, Config(), TODAY)
    assert _verdict(a, "AFF") == "READY"


def test_prerequisites_clear_but_documents_missing_is_blocked():
    p = _project()
    p.states["AFF"] = _state("AFF", status="not_started", granted=None, docs=[])
    a = rules.assess(p, Config(), TODAY)
    r = _readiness(a, "AFF")
    assert r.verdict == "BLOCKED"
    assert "title_deed" in r.missing_documents


def test_an_approval_waiting_on_a_prerequisite_is_blocked():
    p = _project(_all_granted_through(["AFF"]))
    a = rules.assess(p, Config(), TODAY)
    r = _readiness(a, "DCD_DESIGN")
    assert r.verdict == "BLOCKED"
    assert "CONCEPT" in r.missing_prerequisites


# --- the headline case -------------------------------------------------------

def test_filed_without_prerequisites_will_bounce():
    """The expensive failure: already with the authority, and going to be
    rejected on sequence. The cycle spent is unrecoverable."""
    states = _all_granted_through(["AFF", "CONCEPT", "DCD_DESIGN", "SEWER_NOC",
                                   "RTA_NOC", "TELECOM_NOC"])
    states.append(_state("DEWA_NOC", status="filed", filed=date(2026, 6, 10)))
    states.append(_state("BUILDING_PERMIT", status="filed",
                         filed=date(2026, 7, 2)))
    a = rules.assess(_project(states), Config(), TODAY)
    r = _readiness(a, "BUILDING_PERMIT")
    assert r.verdict == "WILL_BOUNCE"
    assert "DEWA_NOC" in r.missing_prerequisites
    assert any("reject on sequence" in x for x in r.reasons)


def test_filed_with_prerequisites_clear_is_merely_filed():
    states = _all_granted_through(["AFF"])
    states.append(_state("CONCEPT", status="filed", filed=date(2026, 8, 1)))
    a = rules.assess(_project(states), Config(), TODAY)
    assert _verdict(a, "CONCEPT") == "FILED"


# --- the caution window ------------------------------------------------------

def test_filing_just_before_a_prerequisite_clears_is_risky():
    """Prerequisite lands inside the caution window, so filing now is a bet
    on the authority being on time."""
    cfg = Config()
    states = _all_granted_through(["AFF"])
    # CONCEPT filed such that its forecast grant is 3 days out.
    cycle = cfg.by_code("CONCEPT").cycle_days
    padded = int(round(cycle * (1 + cfg.forecast_contingency_pct / 100)))
    from datetime import timedelta
    states.append(_state("CONCEPT", status="filed",
                         filed=TODAY + timedelta(days=3) - timedelta(days=padded)))
    a = rules.assess(_project(states), cfg, TODAY)
    assert _verdict(a, "DEWA_NOC") == "RISKY"


def test_a_prerequisite_far_out_is_blocked_not_risky():
    states = _all_granted_through(["AFF"])
    states.append(_state("CONCEPT", status="filed", filed=TODAY))
    a = rules.assess(_project(states), Config(), TODAY)
    assert _verdict(a, "DEWA_NOC") == "BLOCKED"


# --- dates -------------------------------------------------------------------

def test_forecast_carries_contingency():
    """A cycle time quoted without contingency gets treated as a promise."""
    cfg = Config()
    p = _project()
    p.states["AFF"] = _state("AFF", status="not_started", granted=None,
                             docs=["title_deed", "site_plan"])
    a = rules.assess(p, cfg, TODAY)
    r = _readiness(a, "AFF")
    cycle = cfg.by_code("AFF").cycle_days
    expected = int(round(cycle * (1 + cfg.forecast_contingency_pct / 100)))
    assert (r.forecast_grant_date - r.earliest_file_date).days == expected
    assert expected > cycle, "contingency must extend the forecast, not shorten it"


def test_a_granted_approval_contributes_its_actual_date_not_a_forecast():
    states = _all_granted_through(["AFF"])
    states[0].granted_on = date(2026, 5, 8)
    a = rules.assess(_project(states), Config(), TODAY)
    assert _verdict(a, "AFF") == "GRANTED"


def test_completion_forecast_is_later_than_every_intermediate_date():
    p = _project(_all_granted_through(["AFF", "CONCEPT"]))
    a = rules.assess(p, Config(), TODAY)
    intermediates = [r.forecast_grant_date for r in a.readiness
                     if r.forecast_grant_date]
    assert a.forecast_completion >= max(intermediates)


# --- critical path -----------------------------------------------------------

def test_critical_path_ends_at_the_terminal_approval():
    p = _project(_all_granted_through(["AFF"]))
    a = rules.assess(p, Config(), TODAY)
    assert a.critical_path[-1] == "COMPLETION"


def test_critical_path_excludes_granted_approvals():
    p = _project(_all_granted_through(["AFF", "CONCEPT"]))
    a = rules.assess(p, Config(), TODAY)
    assert "AFF" not in a.critical_path
    assert "CONCEPT" not in a.critical_path


def test_critical_path_follows_the_slowest_pending_prerequisite():
    """Five NOCs feed the building permit. The one expected last is the one
    setting the schedule, and it is the one that belongs on the path."""
    from datetime import timedelta
    states = _all_granted_through(["AFF", "CONCEPT", "DCD_DESIGN", "SEWER_NOC",
                                   "RTA_NOC", "TELECOM_NOC"])
    # DEWA_NOC filed recently, so it clears last among the permit's inputs.
    states.append(_state("DEWA_NOC", status="filed", filed=TODAY - timedelta(days=1)))
    a = rules.assess(_project(states), Config(), TODAY)
    assert "DEWA_NOC" in a.critical_path


def test_the_convergence_point_is_not_walked_twice():
    """BUILDING_PERMIT requires five NOCs; a naive walk revisits nodes and
    either loops or explodes. Memoisation must hold."""
    p = _project(_all_granted_through(["AFF"]))
    a = rules.assess(p, Config(), TODAY)
    assert len(a.critical_path) == len(set(a.critical_path))


# --- jurisdiction ------------------------------------------------------------

def test_jurisdiction_selects_the_applicable_graph():
    cfg = Config()
    for j in ("dubai_municipality", "trakhees", "dda", "dubai_south"):
        assert cfg.applicable(j), f"{j} has no applicable approvals"


def test_an_unknown_approval_code_is_reported_not_silently_ignored():
    p = _project()
    p.states["ZZ_UNKNOWN"] = _state("ZZ_UNKNOWN", status="not_started",
                                    granted=None)
    a = rules.assess(p, Config(), TODAY)
    assert any("not in the configured approval graph" in g for g in a.data_gaps)


# --- loading -----------------------------------------------------------------

def _write(text):
    path = os.path.join(tempfile.mkdtemp(), "p.csv")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def test_loader_matches_columns_loosely():
    path = _write("job_no,name,zone,stage,state,date_granted,docs,permit_no\n"
                  "PRJ-009,Tower X,trakhees,AFF,granted,08/05/2026,title_deed,AFF-1\n")
    [p] = projects.load(path)
    assert p.project_id == "PRJ-009"
    assert p.jurisdiction == "trakhees"
    assert p.state("AFF").granted_on == date(2026, 5, 8)
    assert p.state("AFF").reference == "AFF-1"


def test_rows_assemble_into_projects():
    path = _write("project_id,approval_code,status,granted_on\n"
                  "PRJ-A,AFF,granted,2026-05-08\n"
                  "PRJ-A,CONCEPT,not_started,\n"
                  "PRJ-B,AFF,granted,2026-06-08\n")
    loaded = projects.load(path)
    assert {p.project_id for p in loaded} == {"PRJ-A", "PRJ-B"}
    assert len(next(p for p in loaded if p.project_id == "PRJ-A").states) == 2


def test_an_unparseable_date_is_flagged():
    path = _write("project_id,approval_code,status,granted_on\n"
                  "PRJ-A,AFF,granted,2026-13-40\n")
    [p] = projects.load(path)
    assert p.state("AFF").granted_on is None
    assert any("granted_on" in n for n in p.state("AFF").parse_notes)


def test_an_empty_file_is_an_error_not_an_empty_run():
    path = _write("project_id,approval_code\n")
    try:
        projects.load(path)
    except ValueError as exc:
        assert "no project rows" in str(exc)
    else:
        raise AssertionError("an empty file loaded as a clean run")


def test_unknown_config_keys_are_rejected():
    path = os.path.join(tempfile.mkdtemp(), "cfg.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('{"not_a_real_key": 1}')
    try:
        Config.load(path)
    except ValueError as exc:
        assert "unknown config keys" in str(exc)
    else:
        raise AssertionError("a typo in the config loaded silently")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  pass  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL  {name}: {exc}")
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)
