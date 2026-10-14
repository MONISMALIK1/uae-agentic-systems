"""All measurement and claim arithmetic lives here, and only here.

This is the deliberate boundary. Whether a unit's evidence window is good
enough to challenge an allocation, what demand that evidence actually
justifies, and how much money a claim could recover are computed in plain
Python. A language model is never asked to decide any of them.

The reason is specific to what this system produces. The output is a
**claim against a regulated utility**, and claims fail in a particular way:
not by being wrong about direction, but by being too big, or by resting on
evidence that cannot carry them. A provider's engineer reads the claim, finds
the window missed summer or the headroom was ignored, and the whole case --
including the legitimate part -- is dismissed and not re-heard.

So the arithmetic is asymmetric in three places, all pointing the same way:

  1. Evidence sufficiency is a HARD STOP, not a caveat. A window that cannot
     have observed peak demand produces no finding at all.
  2. Justified demand is observed peak PLUS headroom. Claiming down to
     exactly observed peak is engineering nonsense and loses.
  3. The recoverable figure is a CEILING. Everything downstream, including
     the gate, treats it as the maximum a draft may assert.
"""

from dataclasses import dataclass, field
from datetime import date

from . import units as units_mod
from .config import PEAK_MONTHS, Config

# Worst first: the states a person must look at.
STATE_ORDER = ("OVER_ALLOCATED", "UNDER_ALLOCATED", "WITHIN_TOLERANCE",
               "INSUFFICIENT_EVIDENCE", "NOT_ASSESSABLE")


@dataclass
class Finding:
    unit_id: str
    building: str
    state: str
    reasons: list = field(default_factory=list)

    allocated_rt: float = None
    observed_peak_rt: float = None
    justified_rt: float = None
    excess_rt: float = 0.0

    months_observed: int = 0
    peak_months_observed: int = 0
    window: str = ""

    annual_overcharge_aed: float = 0.0
    # The MAXIMUM a claim may assert. Everything downstream treats this as a
    # ceiling, including the gate.
    recoverable_ceiling_aed: float = 0.0
    worth_claiming: bool = False
    points: int = 0


@dataclass
class Portfolio:
    today: date
    findings: list = field(default_factory=list)
    data_gaps: list = field(default_factory=list)

    def by_state(self, state):
        return [f for f in self.findings if f.state == state]

    def claimable(self):
        return [f for f in self.findings
                if f.state == "OVER_ALLOCATED" and f.worth_claiming]

    def total_ceiling_aed(self):
        return round(sum(f.recoverable_ceiling_aed for f in self.claimable()), 2)

    def facts(self):
        """Every identifier and figure an agent may cite.

        `recoverable_ceiling_aed` is handed over explicitly so the gate can
        bound what a draft is allowed to claim.
        """
        return {
            "today": self.today.isoformat(),
            "portfolio_ceiling_aed": self.total_ceiling_aed(),
            "units": [
                {
                    "unit_id": f.unit_id,
                    "building": f.building,
                    "state": f.state,
                    "allocated_rt": f.allocated_rt,
                    "observed_peak_rt": f.observed_peak_rt,
                    "justified_rt": f.justified_rt,
                    "excess_rt": f.excess_rt,
                    "months_observed": f.months_observed,
                    "window": f.window,
                    "annual_overcharge_aed": f.annual_overcharge_aed,
                    "recoverable_ceiling_aed": f.recoverable_ceiling_aed,
                    "reasons": list(f.reasons),
                }
                for f in self.claimable()
            ],
        }


def evidence_quality(readings, cfg: Config):
    """(months, peak_months, window, sufficient).

    Only usable readings count -- a month with no peak figure tells you
    nothing about capacity, however complete its consumption data.
    """
    usable = [r for r in readings if r.is_usable]
    months = len(usable)
    peak_months = sum(1 for r in usable if r.month_number in PEAK_MONTHS)
    window = ""
    if usable:
        ordered = sorted(r.month for r in usable)
        window = f"{ordered[0]} to {ordered[-1]}"
    sufficient = (months >= cfg.min_months_evidence
                  and peak_months >= cfg.min_peak_months)
    return months, peak_months, window, sufficient


def justified_demand(observed_peak: float, cfg: Config) -> float:
    """Observed peak plus legitimate plant headroom.

    Claiming down to exactly observed peak would argue that a system should
    be sized with no margin for a hotter year, equipment ageing or
    simultaneous draw. That argument loses, and it takes the rest of the
    claim with it.
    """
    return round(observed_peak * cfg.headroom_factor, 2)


def assess_unit(unit, readings, cfg: Config, today: date) -> Finding:
    f = Finding(unit_id=unit.unit_id, building=unit.building,
                state="NOT_ASSESSABLE", allocated_rt=unit.allocated_rt)

    if not unit.is_assessable:
        f.reasons.append("no allocation or no capacity rate on record -- a "
                         "missing allocation is not a zero, and nothing can "
                         "be computed from it")
        return f

    months, peak_months, window, sufficient = evidence_quality(readings, cfg)
    f.months_observed, f.peak_months_observed, f.window = months, peak_months, window

    # --- the hard stop ------------------------------------------------------
    if not sufficient:
        f.state = "INSUFFICIENT_EVIDENCE"
        if months < cfg.min_months_evidence:
            f.reasons.append(
                f"{months} usable month(s) of peak-demand data against a "
                f"{cfg.min_months_evidence}-month standard")
        if peak_months < cfg.min_peak_months:
            f.reasons.append(
                f"only {peak_months} of the observed month(s) fall in the "
                f"cooling peak season -- a window that has not seen summer "
                f"cannot establish that an allocation is oversized, it can "
                f"only show the unit was idle in winter")
        f.reasons.append("no claim can rest on this; collect a full season "
                         "before challenging the allocation")
        return f

    usable = [r for r in readings if r.is_usable]
    f.observed_peak_rt = round(max(r.peak_demand_rt for r in usable), 2)
    f.justified_rt = justified_demand(f.observed_peak_rt, cfg)

    # --- under-allocated: reported honestly, even though it costs money -----
    if unit.allocated_rt < f.observed_peak_rt:
        f.state = "UNDER_ALLOCATED"
        f.reasons.append(
            f"observed peak {f.observed_peak_rt:g} RT exceeds the "
            f"{unit.allocated_rt:g} RT allocated -- this unit is at risk of "
            f"undercooling, and correcting it will raise the charge, not "
            f"lower it")
        return f

    # --- within tolerance ---------------------------------------------------
    if unit.allocated_rt <= f.justified_rt * cfg.tolerance_factor:
        f.state = "WITHIN_TOLERANCE"
        f.reasons.append(
            f"{unit.allocated_rt:g} RT allocated against {f.justified_rt:g} RT "
            f"justified (peak {f.observed_peak_rt:g} plus "
            f"{(cfg.headroom_factor - 1) * 100:g}% headroom) -- inside the "
            f"{cfg.tolerance_factor:g}x tolerance, not worth disputing")
        return f

    # --- over-allocated -----------------------------------------------------
    f.state = "OVER_ALLOCATED"
    f.excess_rt = round(unit.allocated_rt - f.justified_rt, 2)
    f.annual_overcharge_aed = round(f.excess_rt * unit.rate_aed_per_rt_year, 2)
    f.recoverable_ceiling_aed = round(
        f.annual_overcharge_aed * cfg.claimable_years, 2)
    f.worth_claiming = f.recoverable_ceiling_aed >= cfg.min_claim_aed

    f.reasons.append(
        f"{unit.allocated_rt:g} RT allocated against {f.justified_rt:g} RT "
        f"justified -- {f.excess_rt:g} RT of excess, observed over {window}")
    f.reasons.append(
        f"{f.annual_overcharge_aed:,.2f} AED per year; "
        f"{f.recoverable_ceiling_aed:,.2f} AED over {cfg.claimable_years} "
        f"year(s) is the CEILING a claim may assert, not a target")
    if not f.worth_claiming:
        f.reasons.append(
            f"below the {cfg.min_claim_aed:,.2f} AED threshold -- the dispute "
            f"costs more than it returns")

    f.points = int(min(100, f.recoverable_ceiling_aed / 1000))
    return f


def assess(unit_rows, reading_rows, cfg: Config, today: date) -> Portfolio:
    gaps = [(u.unit_id, n) for u in unit_rows for n in u.parse_notes]
    gaps += [(r.unit_id, f"{r.month or '(no period)'}: {n}")
             for r in reading_rows for n in r.parse_notes]

    grouped = units_mod.by_unit(reading_rows)
    known = {u.unit_id for u in unit_rows}
    for unit_id in sorted(set(grouped) - known):
        gaps.append((unit_id, f"{len(grouped[unit_id])} reading(s) for a unit "
                              f"not on the allocation schedule"))

    findings = [assess_unit(u, grouped.get(u.unit_id, []), cfg, today)
                for u in unit_rows]
    findings.sort(key=lambda f: (STATE_ORDER.index(f.state),
                                 -f.recoverable_ceiling_aed, f.unit_id))
    return Portfolio(today=today, findings=findings, data_gaps=gaps)
