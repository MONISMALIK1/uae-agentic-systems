"""All projection arithmetic lives here, and only here.

This is the deliberate boundary of the whole system. Where a company will
stand at each target checkpoint, how many hires close the gap, what the
exposure is, and -- the output that matters -- the date after which the
breach becomes arithmetically unavoidable, are all computed in plain Python.
A language model is never asked to decide any of them.

The reason is specific. This system's failure mode is not a wrong number. It
is **false reassurance**: a company told it is on track does nothing, and the
penalty accrues silently until a deadline that was already unreachable months
earlier. An error in the pessimistic direction costs a firm an unnecessary
requisition. An error in the reassuring direction costs them the year.

So the arithmetic is deliberately asymmetric in three places:

  1. Compliance is decided on the COMMITTED projection -- accepted offers
     only. A plan that works when every offer lands and nobody resigns is
     not a plan.
  2. A year with no published target returns None, never zero. Assuming zero
     would report every company as comfortably compliant.
  3. A missing headcount is an unknown, never a zero. Zero Emirati staff is a
     breach; an unreadable figure is a gap, and they must not produce the
     same report.
"""

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import roster as roster_mod
from .config import Config

# Worst first: the two breach states are the ones a person must see.
STATE_ORDER = ("BREACH_LOCKED", "BREACH_AVOIDABLE", "AT_RISK", "COMPLIANT",
               "NOT_APPLICABLE", "INSUFFICIENT_DATA")

BREACH_STATES = ("BREACH_LOCKED", "BREACH_AVOIDABLE")


@dataclass
class Checkpoint:
    """One target year, projected."""
    year: int
    deadline: date
    target_pct: float

    projected_skilled: int = 0
    committed_emirati: int = 0        # accepted offers only
    pipeline_emirati: int = 0         # the whole pipeline
    required_emirati: int = 0

    committed_gap: int = 0            # what decides compliance
    pipeline_gap: int = 0             # what decides AT_RISK vs BREACH

    last_safe_requisition: date = None
    runway_days: int = None
    exposure_aed: float = 0.0
    state: str = "COMPLIANT"
    reasons: list = field(default_factory=list)


@dataclass
class Projection:
    company_id: str
    company_name: str
    as_of: date
    state: str = "COMPLIANT"
    checkpoints: list = field(default_factory=list)
    reasons: list = field(default_factory=list)
    data_gaps: list = field(default_factory=list)
    cited_events: list = field(default_factory=list)

    @property
    def in_breach(self) -> bool:
        return self.state in BREACH_STATES

    def worst(self):
        for s in STATE_ORDER:
            for c in self.checkpoints:
                if c.state == s:
                    return c
        return None

    def facts(self):
        """Every identifier and figure an agent may cite for this company."""
        return {
            "company_id": self.company_id,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "state": self.state,
            "requisitions": list(self.cited_events),
            "checkpoints": [
                {
                    "year": c.year,
                    "deadline": c.deadline.isoformat(),
                    "target_pct": c.target_pct,
                    "projected_skilled": c.projected_skilled,
                    "committed_emirati": c.committed_emirati,
                    "required_emirati": c.required_emirati,
                    "committed_gap": c.committed_gap,
                    "pipeline_gap": c.pipeline_gap,
                    "last_safe_requisition": (c.last_safe_requisition.isoformat()
                                              if c.last_safe_requisition else None),
                    "runway_days": c.runway_days,
                    "exposure_aed": c.exposure_aed,
                    "state": c.state,
                    "reasons": list(c.reasons),
                }
                for c in self.checkpoints
            ],
        }


def required_emirati(skilled_roles: int, target_pct: float) -> int:
    """How many Emirati skilled roles the target implies.

    Rounded UP. A fractional requirement is met by a whole person, and
    rounding down would report a company as compliant while one position
    short.
    """
    return math.ceil(skilled_roles * target_pct / 100.0)


def project_headcount(snapshot, events, at: date, cfg: Config, committed_only: bool):
    """(skilled_roles, emirati_skilled) projected to a date.

    Events without a date are ignored rather than assumed imminent -- an
    undated hire is a hope, and hopes do not change a headcount.
    """
    stages = cfg.committed_stages if committed_only else cfg.pipeline_stages
    skilled = snapshot.skilled_roles
    emirati = snapshot.emirati_skilled

    for e in events:
        if e.expected_date is None or e.expected_date > at:
            continue
        if e.expected_date < snapshot.as_of:
            continue
        if not e.is_skilled:
            continue
        # An exit is always counted, at every confidence level. A resignation
        # is not a plan that might not land -- it is a hole. Counting exits
        # only in the optimistic projection would make the committed number
        # flattering, which is the one direction this tool must not err in.
        if e.event_type == "exit":
            skilled -= 1
            if e.is_emirati:
                emirati -= 1
            continue
        if e.stage not in stages:
            continue
        skilled += 1
        if e.is_emirati:
            emirati += 1

    return max(0, skilled), max(0, emirati)


def assess_checkpoint(snapshot, events, year: int, cfg: Config,
                      today: date) -> Checkpoint:
    target = cfg.target_for(year)
    deadline = date(year, 12, 31)
    c = Checkpoint(year=year, deadline=deadline, target_pct=target or 0.0)

    skilled_c, emirati_c = project_headcount(snapshot, events, deadline, cfg,
                                             committed_only=True)
    _, emirati_p = project_headcount(snapshot, events, deadline, cfg,
                                     committed_only=False)

    c.projected_skilled = skilled_c
    c.committed_emirati = emirati_c
    c.pipeline_emirati = emirati_p
    c.required_emirati = required_emirati(skilled_c, target)
    c.committed_gap = max(0, c.required_emirati - emirati_c)
    c.pipeline_gap = max(0, c.required_emirati - emirati_p)

    # The runway: the last date a requisition opened today could still land
    # before the deadline.
    c.last_safe_requisition = deadline - timedelta(days=cfg.time_to_hire_days)
    c.runway_days = (c.last_safe_requisition - today).days

    if c.committed_gap == 0:
        headroom = emirati_c - c.required_emirati
        if headroom >= cfg.comfort_margin_roles:
            c.state = "COMPLIANT"
            c.reasons.append(
                f"{emirati_c} committed against {c.required_emirati} required "
                f"at {target:g}% of {skilled_c} skilled roles -- "
                f"{headroom} role(s) of headroom")
        else:
            c.state = "AT_RISK"
            c.reasons.append(
                f"exactly on target with {headroom} role(s) of headroom -- one "
                f"resignation puts this company in breach")
        return c

    # There is a gap on the committed projection.
    if c.pipeline_gap == 0:
        c.state = "AT_RISK"
        c.reasons.append(
            f"{c.committed_gap} role(s) short on accepted offers alone; the "
            f"gap closes only if every open requisition lands")
    elif c.runway_days is not None and c.runway_days < 0:
        c.state = "BREACH_LOCKED"
        c.reasons.append(
            f"{c.pipeline_gap} role(s) short with the hiring runway closed "
            f"{abs(c.runway_days)} day(s) ago -- at a {cfg.time_to_hire_days}-day "
            f"time-to-hire, a requisition opened today cannot land before "
            f"{deadline.isoformat()}")
    else:
        c.state = "BREACH_AVOIDABLE"
        c.reasons.append(
            f"{c.pipeline_gap} role(s) short, with {c.runway_days} day(s) of "
            f"runway left -- requisitions must open by "
            f"{c.last_safe_requisition.isoformat()}")

    gap_for_exposure = c.pipeline_gap or c.committed_gap
    months = max(1, (deadline.year - today.year) * 12 + deadline.month - today.month)
    c.exposure_aed = round(
        gap_for_exposure * cfg.penalty_per_unfilled_per_month_aed * months, 2)
    c.reasons.append(
        f"exposure if unfilled: {c.exposure_aed:,.2f} AED "
        f"({gap_for_exposure} role(s) x {months} month(s))")
    return c


def assess(snapshot, events, cfg: Config, today: date) -> Projection:
    p = Projection(company_id=snapshot.company_id,
                   company_name=snapshot.company_name, as_of=snapshot.as_of)

    p.data_gaps = list(snapshot.parse_notes)
    for e in events:
        p.data_gaps.extend(f"{e.event_id}: {n}" for n in e.parse_notes)
    p.cited_events = [e.event_id for e in events if e.event_id]

    if not snapshot.is_projectable:
        p.state = "INSUFFICIENT_DATA"
        p.reasons.append("the snapshot is missing a date or a headcount, so "
                         "nothing can be projected -- an absent count is not "
                         "a zero")
        return p

    if snapshot.skilled_roles < cfg.applies_above_skilled_roles:
        p.state = "NOT_APPLICABLE"
        p.reasons.append(
            f"{snapshot.skilled_roles} skilled roles is below the "
            f"{cfg.applies_above_skilled_roles}-role threshold; verify the "
            f"threshold and its basis before relying on this")
        return p

    years = sorted(int(y) for y in cfg.targets)
    projectable = [y for y in years if y >= today.year]
    if not projectable:
        p.state = "INSUFFICIENT_DATA"
        p.reasons.append("no target year at or after the run date is "
                         "configured -- a year with no published target "
                         "cannot be projected, and is not a zero target")
        return p

    p.checkpoints = [assess_checkpoint(snapshot, events, y, cfg, today)
                     for y in projectable]

    for s in STATE_ORDER:
        if any(c.state == s for c in p.checkpoints):
            p.state = s
            break

    worst = p.worst()
    if worst is not None:
        p.reasons.extend(worst.reasons)
    return p


@dataclass
class Portfolio:
    today: date
    projections: list = field(default_factory=list)

    def by_state(self, state):
        return [p for p in self.projections if p.state == state]

    def in_breach(self):
        return [p for p in self.projections if p.in_breach]

    def total_exposure(self):
        return round(sum(c.exposure_aed for p in self.projections
                         for c in p.checkpoints), 2)


def assess_all(snapshots, events, cfg: Config, today: date) -> Portfolio:
    grouped = roster_mod.by_company(events)
    projections = [assess(s, grouped.get(s.company_id, []), cfg, today)
                   for s in snapshots]
    projections.sort(key=lambda p: (STATE_ORDER.index(p.state), p.company_id))
    return Portfolio(today=today, projections=projections)
