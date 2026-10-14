"""The measurement arithmetic: evidence sufficiency, justified demand, ceiling.

The assertion this file defends: a unit whose evidence window cannot have
observed peak demand produces NO FINDING. Not a weak one -- none.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date  # noqa: E402

from mizan import rules, units  # noqa: E402
from mizan.config import PEAK_MONTHS, Config  # noqa: E402

TODAY = date(2026, 12, 1)


def _unit(**kw):
    base = dict(unit_id="UNT-0101", building="Marina Heights",
                unit_type="retail", allocated_rt=45.0,
                rate_aed_per_rt_year=3200.0, owner_ref="OWN-5501")
    base.update(kw)
    return units.Unit(**base)


def _readings(peaks_by_month):
    """peaks_by_month: list of (month_str, peak)."""
    return [units.Reading(unit_id="UNT-0101", month=m, peak_demand_rt=p,
                          consumption_rt_hours=p * 400)
            for m, p in peaks_by_month]


def _full_year(peak=18.0):
    out = []
    for y, m in [(2026, i) for i in range(1, 13)] + [(2025, 11), (2025, 12)]:
        out.append((f"{y}-{m:02d}", peak if m in PEAK_MONTHS else peak * 0.4))
    return _readings(out)


def _assess(unit=None, readings=None, cfg=None):
    return rules.assess_unit(unit or _unit(), readings or _full_year(),
                             cfg or Config(), TODAY)


# --- the hard stop: evidence that cannot have seen the peak -----------------

def test_a_winter_only_window_produces_no_finding():
    """The central assertion. A window that missed summer can only show the
    unit was idle in winter, which is not a finding about capacity."""
    winter = _readings([("2025-11", 6.0), ("2025-12", 5.8), ("2026-01", 5.5),
                        ("2026-02", 5.6), ("2026-03", 6.2)])
    f = _assess(readings=winter)
    assert f.state == "INSUFFICIENT_EVIDENCE"
    assert f.recoverable_ceiling_aed == 0.0
    assert f.excess_rt == 0.0
    assert any("has not seen summer" in r for r in f.reasons)


def test_a_full_year_missing_the_peak_months_is_still_insufficient():
    cfg = Config()
    no_summer = _readings([(f"2026-{m:02d}", 8.0)
                           for m in (1, 2, 3, 4, 5, 10, 11, 12)]
                          + [(f"2025-{m:02d}", 8.0) for m in (9, 10, 11, 12)])
    # 12 months, but only one peak-season month (2025-09).
    f = _assess(readings=no_summer, cfg=cfg)
    assert f.peak_months_observed < cfg.min_peak_months
    assert f.state == "INSUFFICIENT_EVIDENCE"


def test_too_few_months_is_insufficient_even_with_summer():
    short = _readings([("2026-07", 18.0), ("2026-08", 18.2), ("2026-09", 17.0)])
    f = _assess(readings=short)
    assert f.state == "INSUFFICIENT_EVIDENCE"


def test_readings_without_a_peak_figure_do_not_count_as_evidence():
    """Consumption cannot stand in for peak: a flat heavy month and a month
    with one brief spike can have identical RT-hours."""
    rs = [units.Reading("UNT-0101", f"2026-{m:02d}", None, 5000.0)
          for m in range(1, 13)]
    f = _assess(readings=rs)
    assert f.months_observed == 0
    assert f.state == "INSUFFICIENT_EVIDENCE"


# --- justified demand --------------------------------------------------------

def test_justified_demand_is_peak_plus_headroom():
    cfg = Config()
    assert rules.justified_demand(20.0, cfg) == round(20.0 * cfg.headroom_factor, 2)


def test_headroom_is_above_one_so_a_claim_never_argues_for_zero_margin():
    assert Config().headroom_factor > 1.0


def test_the_claim_is_measured_against_justified_not_observed_peak():
    cfg = Config()
    f = _assess(cfg=cfg)
    assert f.excess_rt == round(f.allocated_rt - f.justified_rt, 2)
    assert f.justified_rt > f.observed_peak_rt


# --- the states --------------------------------------------------------------

def test_a_clearly_oversized_allocation_is_over_allocated():
    f = _assess()
    assert f.state == "OVER_ALLOCATED"
    assert f.excess_rt > 0 and f.recoverable_ceiling_aed > 0


def test_an_allocation_inside_tolerance_is_not_challenged():
    cfg = Config()
    # peak 22 -> justified 25.3 -> tolerance ceiling 31.6
    f = _assess(_unit(allocated_rt=30.0), _full_year(peak=22.0), cfg)
    assert f.state == "WITHIN_TOLERANCE"
    assert f.recoverable_ceiling_aed == 0.0


def test_an_allocation_below_observed_peak_is_reported_honestly():
    """Reporting this costs the client money. It is still the truth."""
    f = _assess(_unit(allocated_rt=12.0), _full_year(peak=15.0))
    assert f.state == "UNDER_ALLOCATED"
    assert any("undercooling" in r for r in f.reasons)
    assert f.recoverable_ceiling_aed == 0.0


def test_a_missing_allocation_is_not_assessable_not_a_total_overcharge():
    f = _assess(_unit(allocated_rt=None))
    assert f.state == "NOT_ASSESSABLE"
    assert f.recoverable_ceiling_aed == 0.0


def test_a_missing_rate_is_not_assessable():
    f = _assess(_unit(rate_aed_per_rt_year=None))
    assert f.state == "NOT_ASSESSABLE"


# --- the ceiling -------------------------------------------------------------

def test_the_ceiling_is_the_annual_overcharge_times_the_claimable_years():
    cfg = Config()
    f = _assess(cfg=cfg)
    assert f.recoverable_ceiling_aed == round(
        f.annual_overcharge_aed * cfg.claimable_years, 2)


def test_a_small_overcharge_is_not_worth_claiming():
    cfg = Config()
    cfg.min_claim_aed = 1_000_000.0
    f = _assess(cfg=cfg)
    assert f.state == "OVER_ALLOCATED"
    assert f.worth_claiming is False


def test_only_claimable_units_reach_the_portfolio_ceiling():
    cfg = Config()
    over = _assess(cfg=cfg)
    under = rules.assess_unit(_unit(unit_id="UNT-0103", allocated_rt=12.0),
                              _full_year(peak=15.0), cfg, TODAY)
    pf = rules.Portfolio(today=TODAY, findings=[over, under])
    assert pf.total_ceiling_aed() == over.recoverable_ceiling_aed


def test_facts_expose_only_claimable_units():
    cfg = Config()
    blocked = rules.assess_unit(_unit(unit_id="UNT-0104"),
                                _readings([("2026-01", 6.0)]), cfg, TODAY)
    over = _assess(cfg=cfg)
    pf = rules.Portfolio(today=TODAY, findings=[over, blocked])
    ids = {u["unit_id"] for u in pf.facts()["units"]}
    assert "UNT-0104" not in ids, "a unit with no finding must not be offered to an agent"


# --- loading -----------------------------------------------------------------

def _write(text, name="f.csv"):
    path = os.path.join(tempfile.mkdtemp(), name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def test_unit_loader_matches_columns_loosely():
    path = _write("premise_no,tower,use,contracted_rt,rt_rate\n"
                  "UNT-9,Marina,retail,45,3200\n")
    [u] = units.load_units(path)
    assert u.unit_id == "UNT-9" and u.allocated_rt == 45.0


def test_an_unparseable_allocation_is_a_gap_never_a_zero():
    path = _write("unit_id,allocated_rt,rate_aed_per_rt_year\n"
                  "UNT-9,n/a,3200\n")
    [u] = units.load_units(path)
    assert u.allocated_rt is None and u.is_assessable is False


def test_month_formats_normalise():
    path = _write("unit_id,month,peak_demand_rt\n"
                  "UNT-9,07/2026,18\n", "r.csv")
    [r] = units.load_readings(path)
    assert r.month == "2026-07" and r.month_number == 7


def test_an_unparseable_month_is_flagged_and_unusable():
    path = _write("unit_id,month,peak_demand_rt\n"
                  "UNT-9,not-a-month,18\n", "r.csv")
    [r] = units.load_readings(path)
    assert r.is_usable is False
    assert any("cannot be placed in a season" in n for n in r.parse_notes)


def test_readings_for_an_unknown_unit_are_surfaced():
    cfg = Config()
    pf = rules.assess([_unit()],
                      _full_year() + [units.Reading("UNT-9999", "2026-07", 11.0)],
                      cfg, TODAY)
    assert any("not on the allocation schedule" in n for _, n in pf.data_gaps)


def test_an_empty_units_file_is_an_error():
    path = _write("unit_id,building\n")
    try:
        units.load_units(path)
    except ValueError as exc:
        assert "no units" in str(exc)
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
