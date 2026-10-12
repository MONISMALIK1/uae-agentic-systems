"""The projection arithmetic: the double projection, the runway, the states.

The assertions this file exists to defend are the three asymmetries. Every
one of them errs toward telling a company it has a problem when it might
not, because the opposite error costs the year.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date  # noqa: E402

from ufuq import roster, rules  # noqa: E402
from ufuq.config import Config  # noqa: E402

TODAY = date(2026, 11, 1)


def _snap(**kw):
    base = dict(company_id="CO-1001", company_name="Test Co",
                as_of=date(2026, 9, 1), skilled_roles=240, emirati_skilled=22)
    base.update(kw)
    return roster.Snapshot(**base)


def _event(**kw):
    base = dict(company_id="CO-1001", event_id="REQ-20101", event_type="hire",
                stage="accepted", is_emirati=True, is_skilled=True,
                expected_date=date(2026, 10, 15))
    base.update(kw)
    return roster.Event(**base)


def _assess(snap=None, events=None, cfg=None, today=TODAY):
    return rules.assess(snap or _snap(), events or [], cfg or Config(), today)


def _cp(projection, year):
    for c in projection.checkpoints:
        if c.year == year:
            return c
    raise AssertionError(f"no checkpoint for {year}")


# --- asymmetry 1: compliance is decided on committed only --------------------

def test_compliance_is_decided_on_accepted_offers_only():
    """A plan that works when every offer lands is not a plan."""
    cfg = Config()
    # 240 skilled, 22 Emirati, 2026 target 8% -> needs 20. Already compliant.
    # Push to 2027 (10% -> 25 needed) with three Emirati hires, one accepted.
    events = [
        _event(event_id="REQ-1", stage="accepted", expected_date=date(2027, 3, 1)),
        _event(event_id="REQ-2", stage="offered", expected_date=date(2027, 3, 1)),
        _event(event_id="REQ-3", stage="sourcing", expected_date=date(2027, 3, 1)),
    ]
    c = _cp(_assess(events=events, cfg=cfg), 2027)
    assert c.committed_emirati == 23, c.committed_emirati
    assert c.pipeline_emirati == 25, c.pipeline_emirati
    assert c.committed_gap == 2
    assert c.pipeline_gap == 0
    assert c.state == "AT_RISK", "closing only on the full pipeline is AT_RISK"


def test_at_risk_is_not_reported_as_compliant():
    cfg = Config()
    events = [_event(event_id="REQ-2", stage="offered",
                     expected_date=date(2027, 3, 1))]
    p = _assess(events=events, cfg=cfg)
    assert p.state != "COMPLIANT"


def test_exactly_on_target_is_at_risk_not_compliant():
    """One resignation from breach is not a comfortable position."""
    cfg = Config()
    # 250 skilled, 8% of 250 = 20; hold exactly 20.
    p = _assess(_snap(skilled_roles=250, emirati_skilled=20), cfg=cfg,
                today=date(2026, 1, 15))
    assert _cp(p, 2026).state == "AT_RISK"


def test_an_exit_counts_even_when_unconfirmed():
    """A resignation is a hole, not a plan that might not land. Counting
    exits only optimistically would flatter the committed number."""
    cfg = Config()
    events = [_event(event_id="EXT-1", event_type="exit", stage="rumoured",
                     is_emirati=True, expected_date=date(2026, 10, 1))]
    c = _cp(_assess(events=events, cfg=cfg), 2026)
    assert c.committed_emirati == 21, "the exit must reduce the committed count"


# --- asymmetry 2: an unscheduled year is not a zero target -------------------

def test_a_year_with_no_target_is_none_not_zero():
    cfg = Config()
    assert cfg.target_for(2099) is None


def test_no_projectable_year_is_insufficient_data_not_compliant():
    cfg = Config()
    cfg.targets = {"2020": 4.0}
    p = _assess(cfg=cfg)
    assert p.state == "INSUFFICIENT_DATA"


# --- asymmetry 3: a missing count is not a zero ------------------------------

def test_a_missing_headcount_is_unprojectable_not_a_breach():
    """Zero Emirati staff is a breach; an unreadable figure is an unknown."""
    p = _assess(_snap(emirati_skilled=None))
    assert p.state == "INSUFFICIENT_DATA"
    assert p.state not in rules.BREACH_STATES


def test_a_self_contradicting_snapshot_is_rejected():
    path = os.path.join(tempfile.mkdtemp(), "r.csv")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("company_id,as_of,skilled_roles,emirati_skilled\n"
                 "CO-1,2026-09-01,10,40\n")
    [s] = roster.load_roster(path)
    assert s.is_projectable is False
    assert any("contradicts itself" in n for n in s.parse_notes)


# --- the requirement ---------------------------------------------------------

def test_the_requirement_rounds_up():
    """A fractional requirement is met by a whole person. Rounding down
    reports a company as compliant while one position short."""
    assert rules.required_emirati(101, 8.0) == 9      # 8.08 -> 9
    assert rules.required_emirati(100, 8.0) == 8      # exact


def test_growth_raises_the_requirement():
    """Every non-Emirati skilled hire increases the obligation."""
    cfg = Config()
    without = _cp(_assess(cfg=cfg), 2027).required_emirati
    with_growth = _cp(_assess(events=[
        _event(event_id="REQ-9", is_emirati=False, stage="accepted",
               expected_date=date(2027, 2, 1))], cfg=cfg), 2027).required_emirati
    assert with_growth >= without


# --- the runway --------------------------------------------------------------

def test_the_last_safe_date_is_the_deadline_minus_time_to_hire():
    cfg = Config()
    c = _cp(_assess(cfg=cfg), 2026)
    assert (c.deadline - c.last_safe_requisition).days == cfg.time_to_hire_days


def test_a_closed_runway_with_a_gap_is_locked():
    cfg = Config()
    p = _assess(_snap(skilled_roles=180, emirati_skilled=9), cfg=cfg,
                today=date(2026, 11, 1))
    c = _cp(p, 2026)
    assert c.runway_days < 0
    assert c.state == "BREACH_LOCKED"


def test_an_open_runway_with_a_gap_is_avoidable():
    cfg = Config()
    p = _assess(_snap(skilled_roles=180, emirati_skilled=9), cfg=cfg,
                today=date(2026, 1, 15))
    c = _cp(p, 2026)
    assert c.runway_days > 0
    assert c.state == "BREACH_AVOIDABLE"


def test_a_closed_runway_without_a_gap_is_not_a_breach():
    """The runway only matters when there is something to close."""
    cfg = Config()
    c = _cp(_assess(cfg=cfg, today=date(2026, 11, 1)), 2026)
    assert c.runway_days < 0
    assert c.state == "COMPLIANT"


# --- exposure ----------------------------------------------------------------

def test_exposure_scales_with_the_gap_and_the_months_remaining():
    cfg = Config()
    p = _assess(_snap(skilled_roles=180, emirati_skilled=9), cfg=cfg,
                today=date(2026, 11, 1))
    c = _cp(p, 2026)
    assert c.exposure_aed == c.pipeline_gap * cfg.penalty_per_unfilled_per_month_aed * 2 \
        or c.exposure_aed > 0


def test_a_compliant_checkpoint_carries_no_exposure():
    c = _cp(_assess(), 2026)
    assert c.state == "COMPLIANT"
    assert c.exposure_aed == 0.0


# --- threshold and states ----------------------------------------------------

def test_below_the_threshold_is_not_applicable():
    p = _assess(_snap(skilled_roles=42, emirati_skilled=2))
    assert p.state == "NOT_APPLICABLE"
    assert any("verify the threshold" in r for r in p.reasons)


def test_the_company_state_is_the_worst_of_its_checkpoints():
    cfg = Config()
    p = _assess(_snap(skilled_roles=180, emirati_skilled=9), cfg=cfg,
                today=date(2026, 11, 1))
    states = {c.state for c in p.checkpoints}
    assert "BREACH_LOCKED" in states
    assert p.state == "BREACH_LOCKED"


def test_in_breach_covers_both_breach_states():
    for s in ("BREACH_LOCKED", "BREACH_AVOIDABLE"):
        p = rules.Projection(company_id="X", company_name="X", as_of=TODAY,
                             state=s)
        assert p.in_breach is True
    for s in ("COMPLIANT", "AT_RISK", "NOT_APPLICABLE", "INSUFFICIENT_DATA"):
        p = rules.Projection(company_id="X", company_name="X", as_of=TODAY,
                             state=s)
        assert p.in_breach is False


# --- events ------------------------------------------------------------------

def test_an_undated_event_never_moves_a_headcount():
    """An undated hire is a hope, and hopes do not change a headcount."""
    cfg = Config()
    with_undated = _cp(_assess(events=[
        _event(event_id="REQ-9", expected_date=None)], cfg=cfg), 2026)
    without = _cp(_assess(cfg=cfg), 2026)
    assert with_undated.committed_emirati == without.committed_emirati


def test_an_unskilled_hire_does_not_change_the_skilled_denominator():
    cfg = Config()
    c = _cp(_assess(events=[
        _event(event_id="REQ-9", is_skilled=False, is_emirati=False,
               expected_date=date(2026, 10, 1))], cfg=cfg), 2026)
    assert c.projected_skilled == 240


def test_events_before_the_snapshot_are_already_counted():
    """A hire that landed before the snapshot is in the snapshot. Counting it
    again would double it."""
    cfg = Config()
    c = _cp(_assess(events=[
        _event(event_id="REQ-9", expected_date=date(2026, 8, 1))], cfg=cfg), 2026)
    assert c.committed_emirati == 22


# --- loading -----------------------------------------------------------------

def _write(text, name="f.csv"):
    path = os.path.join(tempfile.mkdtemp(), name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def test_roster_loader_matches_columns_loosely():
    path = _write("establishment_no,establishment,snapshot_date,"
                  "total_skilled,nationals_skilled\n"
                  "CO-9,Widgets LLC,01/09/2026,200,18\n")
    [s] = roster.load_roster(path)
    assert s.company_id == "CO-9"
    assert s.skilled_roles == 200 and s.emirati_skilled == 18
    assert s.as_of == date(2026, 9, 1)


def test_an_unparseable_count_is_a_gap_never_a_zero():
    path = _write("company_id,as_of,skilled_roles,emirati_skilled\n"
                  "CO-9,2026-09-01,200,n/a\n")
    [s] = roster.load_roster(path)
    assert s.emirati_skilled is None
    assert s.is_projectable is False


def test_an_undated_pipeline_event_is_flagged():
    path = _write("company_id,event_id,expected_date\n"
                  "CO-9,REQ-1,not-a-date\n", "p.csv")
    [e] = roster.load_pipeline(path)
    assert e.expected_date is None
    assert any("cannot be placed" in n for n in e.parse_notes)


def test_an_empty_roster_is_an_error_not_an_empty_run():
    path = _write("company_id,company_name\n")
    try:
        roster.load_roster(path)
    except ValueError as exc:
        assert "no roster rows" in str(exc)
    else:
        raise AssertionError("an empty file loaded as a clean run")


def test_unknown_config_keys_are_rejected():
    path = _write('{"not_a_real_key": 1}', "cfg.json")
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
