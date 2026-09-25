"""The attribution logic: the custody join, the three states, the clock.

Everything here runs on constructed rows -- no CSV, no network, no model.
The central assertion this file exists to defend: **a contested fine never
names anybody.** If that moves, the system has started making accusations it
cannot support.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date, datetime  # noqa: E402

from athar import assignments, fines, rules  # noqa: E402
from athar.config import Config  # noqa: E402

TODAY = date(2026, 9, 22)


def _fine(**kw):
    base = dict(fine_id="FN-00001", plate="A12345",
                issued_at=datetime(2026, 9, 2, 14, 22),
                received_at=date(2026, 9, 14), source="dubai_police",
                location="Sheikh Zayed Road", amount_aed=600.0, black_points=0)
    base.update(kw)
    return fines.Fine(**base)


def _asg(**kw):
    base = dict(assignment_id="ASG-00101", plate="A12345", driver_id="DRV-4401",
                driver_name="M. Haddad", kind="rental",
                start_at=datetime(2026, 9, 1, 9, 0),
                end_at=datetime(2026, 9, 4, 18, 0),
                contract_ref="RC-2026-8842", handover_doc="HO-2026-3311")
    base.update(kw)
    return assignments.Assignment(**base)


def _attr(fine=None, asgs=None, cfg=None):
    return rules.attribute(fine or _fine(), asgs if asgs is not None else [_asg()],
                           cfg or Config(), TODAY)


# --- the invariant this system exists to hold --------------------------------

def test_a_contested_fine_never_names_anybody():
    """The whole safety property. A boundary-adjacent violation must not
    attach to the person on either side of it."""
    a = _attr(_fine(issued_at=datetime(2026, 9, 1, 9, 20)))
    assert a.state == "CONTESTED"
    assert a.names_a_person is False
    assert a.driver_id == "" and a.driver_name == ""


def test_an_overlapping_record_contests_rather_than_picking_one():
    a = _attr(_fine(issued_at=datetime(2026, 9, 2, 12, 0)),
              [_asg(), _asg(assignment_id="ASG-00102", driver_id="DRV-4402",
                            start_at=datetime(2026, 9, 1, 9, 0),
                            end_at=datetime(2026, 9, 4, 18, 0))])
    assert a.state == "CONTESTED"
    assert a.names_a_person is False
    assert set(a.candidates) == {"ASG-00101", "ASG-00102"}


def test_company_and_unattributable_states_also_name_nobody():
    no_cover = _attr(_fine(issued_at=datetime(2026, 9, 20, 10, 0)))
    no_stamp = _attr(_fine(issued_at=None))
    assert no_cover.state == "COMPANY" and no_cover.names_a_person is False
    assert no_stamp.state == "UNATTRIBUTABLE" and no_stamp.names_a_person is False


# --- the join ----------------------------------------------------------------

def test_a_clean_interior_violation_is_attributed():
    a = _attr(_fine(issued_at=datetime(2026, 9, 2, 14, 22)))
    assert a.state == "ATTRIBUTED"
    assert a.driver_id == "DRV-4401"
    assert a.assignment_id == "ASG-00101"


def test_an_open_ended_assignment_covers_everything_after_its_start():
    a = _attr(_fine(issued_at=datetime(2026, 12, 1, 10, 0)),
              [_asg(end_at=None)])
    assert a.state == "ATTRIBUTED"


def test_a_violation_before_any_custody_is_company_borne():
    a = _attr(_fine(issued_at=datetime(2026, 8, 30, 10, 0)))
    assert a.state == "COMPANY"


def test_no_custody_records_at_all_is_company_borne():
    a = _attr(_fine(), [])
    assert a.state == "COMPANY"
    assert "company's own hands" in " ".join(a.reasons)


def test_covers_is_inclusive_at_both_edges():
    asg = _asg()
    assert rules.covers(asg, asg.start_at) is True
    assert rules.covers(asg, asg.end_at) is True


def test_an_assignment_with_no_start_is_not_a_custody_claim():
    assert _asg(start_at=None).is_usable is False


# --- the handover buffer -----------------------------------------------------

def test_the_buffer_is_measured_from_both_edges():
    cfg = Config()
    asg = _asg()
    just_after_start = datetime(2026, 9, 1, 9, 30)
    just_before_end = datetime(2026, 9, 4, 17, 30)
    assert rules.near_boundary(asg, just_after_start, cfg.handover_buffer_minutes)
    assert rules.near_boundary(asg, just_before_end, cfg.handover_buffer_minutes)


def test_outside_the_buffer_is_safe():
    cfg = Config()
    asg = _asg()
    middle = datetime(2026, 9, 2, 12, 0)
    assert rules.near_boundary(asg, middle, cfg.handover_buffer_minutes) is False


def test_a_wider_buffer_contests_more_not_less():
    """The knob only ever moves toward caution."""
    when = datetime(2026, 9, 1, 10, 30)     # 90 minutes after start
    narrow = Config()
    narrow.handover_buffer_minutes = 45
    wide = Config()
    wide.handover_buffer_minutes = 120
    assert _attr(_fine(issued_at=when), cfg=narrow).state == "ATTRIBUTED"
    assert _attr(_fine(issued_at=when), cfg=wide).state == "CONTESTED"


# --- evidence and recoverability ---------------------------------------------

def test_attribution_and_recoverability_are_separate_questions():
    """A fine can be correctly attributed and still unrecoverable. Conflating
    them hides why recovery failed."""
    a = _attr(_fine(issued_at=datetime(2026, 9, 2, 12, 0)),
              [_asg(handover_doc="")])
    assert a.state == "ATTRIBUTED"
    assert a.driver_id == "DRV-4401"
    assert a.recoverable is False
    assert a.missing_evidence == ["handover_doc"]


def test_a_complete_rental_bundle_is_recoverable():
    a = _attr(_fine(issued_at=datetime(2026, 9, 2, 12, 0)))
    assert a.recoverable is True and a.missing_evidence == []


def test_an_employee_attribution_is_flagged_for_labour_law():
    a = _attr(_fine(issued_at=datetime(2026, 9, 2, 12, 0)),
              [_asg(kind="shift", contract_ref="", handover_doc="")])
    assert a.state == "ATTRIBUTED"
    assert a.kind == "shift"
    assert any("labour law" in r for r in a.reasons)


# --- the dispute clock -------------------------------------------------------

def test_the_window_counts_down_from_the_issue_date():
    a = _attr(_fine(issued_at=datetime(2026, 9, 12, 10, 0)))
    assert a.window_days == 30
    assert a.days_to_dispute == 20


def test_an_unknown_source_gets_the_shortest_window_not_a_generous_one():
    """Assuming a long deadline is how a contestable fine goes uncontested."""
    cfg = Config()
    assert cfg.window_days("some_new_authority") == cfg.default_dispute_window_days
    assert cfg.default_dispute_window_days <= min(cfg.dispute_window_days.values())


def test_a_closed_window_drops_out_of_the_actionable_bands():
    a = _attr(_fine(issued_at=datetime(2026, 7, 1, 10, 0), black_points=8))
    assert a.days_to_dispute < 0
    assert a.band == "monitor"
    assert any("window has closed" in r for r in a.reasons)


def test_a_closing_window_scores_urgent():
    # Salik carries a 15-day window; issued 11 days ago leaves 4.
    cfg = Config()
    a = _attr(_fine(source="rta_salik",
                    issued_at=datetime(2026, 9, 11, 10, 0),
                    amount_aed=1500.0), cfg=cfg)
    assert a.days_to_dispute == 4, a.days_to_dispute
    assert a.band == "urgent"


# --- scoring -----------------------------------------------------------------

def test_black_points_raise_priority_independently_of_amount():
    small_with_points = _attr(_fine(amount_aed=200.0, black_points=8,
                                    issued_at=datetime(2026, 9, 2, 12, 0)))
    small_without = _attr(_fine(amount_aed=200.0, black_points=0,
                                issued_at=datetime(2026, 9, 2, 12, 0)))
    assert small_with_points.points > small_without.points


def test_priority_does_not_depend_on_whether_anyone_was_named():
    """A contested fine with a closing window is urgent precisely because
    evidence must be found before the window shuts."""
    # Boundary-adjacent (so contested) on a 30-day police window, still open.
    cfg = Config()
    contested = _attr(_fine(source="dubai_police", amount_aed=1500.0,
                            issued_at=datetime(2026, 9, 1, 9, 20)), cfg=cfg)
    assert contested.state == "CONTESTED"
    assert contested.days_to_dispute > 0
    assert contested.band in ("urgent", "queue")


# --- the ledger --------------------------------------------------------------

def test_exposure_splits_three_ways():
    cfg = Config()
    ledger = rules.assess(
        [_fine(fine_id="FN-1", issued_at=datetime(2026, 9, 2, 12, 0), amount_aed=600.0),
         _fine(fine_id="FN-2", issued_at=datetime(2026, 9, 1, 9, 20), amount_aed=900.0),
         _fine(fine_id="FN-3", issued_at=datetime(2026, 9, 20, 10, 0), amount_aed=300.0)],
        [_asg()], cfg, TODAY)
    rec, contested, company = ledger.exposure_aed()
    assert (rec, contested, company) == (600.0, 900.0, 300.0)


def test_custody_records_for_plates_with_no_fines_are_surfaced():
    ledger = rules.assess([_fine()],
                          [_asg(), _asg(assignment_id="ASG-9", plate="ZZ999")],
                          Config(), TODAY)
    assert any("no fines this run" in n for _, n in ledger.data_gaps)


def test_facts_expose_only_actionable_fines():
    ledger = rules.assess([_fine(issued_at=datetime(2026, 9, 2, 12, 0))],
                          [_asg()], Config(), TODAY)
    facts = ledger.facts()
    assert len(facts["fines"]) == len(ledger.actionable())


# --- loading -----------------------------------------------------------------

def _write(text, name="f.csv"):
    path = os.path.join(tempfile.mkdtemp(), name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def test_fine_loader_matches_columns_loosely():
    path = _write("violation_no,plate_no,violation_datetime,authority,fine_amount\n"
                  "FN-9,A 123 45,02/09/2026 14:22,dubai_police,600\n")
    [f] = fines.load(path)
    assert f.fine_id == "FN-9"
    assert f.plate == "A12345", "plates must normalise for joining"
    assert f.issued_at == datetime(2026, 9, 2, 14, 22)


def test_an_unparseable_timestamp_makes_a_fine_unattributable_not_midnight():
    """A midnight default would silently place the violation inside whichever
    assignment spanned that hour -- a false attribution by rounding."""
    path = _write("fine_id,plate,issued_at\nFN-9,A12345,not-a-timestamp\n")
    [f] = fines.load(path)
    assert f.issued_at is None
    assert any("cannot be attributed" in n for n in f.parse_notes)


def test_an_unparseable_amount_is_a_gap_never_a_zero():
    path = _write("fine_id,plate,amount_aed\nFN-9,A12345,n/a\n")
    [f] = fines.load(path)
    assert f.amount_aed is None
    assert any("amount_aed" in n for n in f.parse_notes)


def test_an_inverted_interval_is_discarded_not_trusted():
    path = _write("assignment_id,plate,start_at,end_at\n"
                  "ASG-9,A12345,2026-09-05 10:00,2026-09-01 10:00\n", "a.csv")
    [a] = assignments.load(path)
    assert a.is_usable is False
    assert any("precedes" in n for n in a.parse_notes)


def test_an_unrecognised_kind_falls_back_and_says_so():
    path = _write("assignment_id,plate,kind,start_at\n"
                  "ASG-9,A12345,leaseback,2026-09-01 09:00\n", "a.csv")
    [a] = assignments.load(path)
    assert a.kind == "rental"
    assert any("wage deduction" in n for n in a.parse_notes)


def test_an_empty_fines_file_is_an_error_not_an_empty_run():
    path = _write("fine_id,plate\n")
    try:
        fines.load(path)
    except ValueError as exc:
        assert "no fines" in str(exc)
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
