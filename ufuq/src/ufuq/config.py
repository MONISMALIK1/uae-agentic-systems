"""Targets, penalties and hiring reality -- and where each one came from.

**Every figure in this file must be verified before anyone acts on it, and
more so than in any other system in this repository.**

The UAE's Emiratisation framework -- the target schedule, the headcount
threshold it applies above, how a "skilled role" is categorised, and the
penalty for an unfilled position -- has been revised more than once, and the
figures below are ILLUSTRATIVE DEFAULTS reconstructed to exercise the
arithmetic. They are not the current schedule and are not legal advice.
Confirm every row against current MOHRE / Nafis rules before relying on a
projection.

What this file encodes that is *not* jurisdiction-specific is the shape of
the problem, and the shape is the interesting part:

  * the target rises on a schedule, so meeting it this year says nothing
    about next year
  * the denominator moves -- every non-Emirati hire raises the number of
    Emirati hires required, so growth quietly increases the obligation
  * hiring takes months, so there is a date after which a breach becomes
    arithmetically unavoidable, and that date arrives long before the
    deadline does

The asymmetry running through the file:

    A projection is computed twice -- once counting only what is committed,
    once counting the whole pipeline -- and the COMMITTED number is the one
    that decides compliance.

A plan that works only if every offer is accepted and nobody resigns is not
a plan. Reporting it as compliance is the specific failure this system
exists to prevent.
"""

import json
from dataclasses import dataclass, asdict, field

MOHRE = "https://www.mohre.gov.ae/"
NAFIS = "https://www.nafis.gov.ae/"


@dataclass
class Config:
    # --- the target schedule ------------------------------------------------
    # year -> required percentage of skilled roles held by UAE nationals.
    # VERIFY EVERY ROW. These are illustrative and rise on a schedule that
    # has been revised.
    targets: dict = field(default_factory=lambda: {
        "2026": 8.0,
        "2027": 10.0,
        "2028": 12.0,
    })

    # The framework applies above this headcount. VERIFY: the threshold has
    # changed, and the basis (total staff vs skilled roles) matters.
    applies_above_skilled_roles: int = 50

    # --- penalty ------------------------------------------------------------
    # Accrued per unfilled position per month. VERIFY -- this figure has been
    # revised and is the single most consequential number in the file, since
    # it is what makes a projection actionable rather than interesting.
    penalty_per_unfilled_per_month_aed: float = 9000.0

    # --- hiring reality -----------------------------------------------------
    # Days from opening a requisition to a start date, for a skilled Emirati
    # hire. VERIFY: this is the firm's OWN historical figure. Using a market
    # average here produces a last-safe-date that is wrong for this company,
    # which is worse than no date at all.
    time_to_hire_days: int = 77

    # How much of the pipeline counts toward the committed projection.
    # Only accepted offers are committed; everything else is optimism, and
    # optimism is projected separately rather than blended in.
    committed_stages: tuple = ("accepted",)
    pipeline_stages: tuple = ("accepted", "offered", "sourcing")

    # Roles of headroom before a company is called comfortable. A company
    # exactly on target is one resignation from breach.
    comfort_margin_roles: int = 1

    # --- banding ------------------------------------------------------------
    # Days of runway left before the situation is urgent.
    urgent_runway_days: int = 30

    sources: dict = field(default_factory=lambda: {
        "targets": "MOHRE / Nafis schedule -- VERIFY, revised more than once",
        "penalty_per_unfilled_per_month_aed": "MOHRE penalty schedule -- VERIFY",
        "applies_above_skilled_roles": "MOHRE threshold -- VERIFY",
        "time_to_hire_days": "the firm's own historical figure, not a market average",
    })

    VERIFY_FIELDS = ("targets", "penalty_per_unfilled_per_month_aed",
                     "applies_above_skilled_roles", "time_to_hire_days")

    def target_for(self, year: int):
        """Required percentage for a year, or None if not scheduled.

        None is not zero. A year with no published target is a year this tool
        cannot project, and saying so is the honest output -- assuming zero
        would report every company as comfortably compliant.
        """
        return self.targets.get(str(year))

    def to_dict(self):
        return asdict(self)

    @classmethod
    def load(cls, path=None):
        cfg = cls()
        if not path:
            return cfg
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        unknown = set(data) - set(asdict(cfg))
        if unknown:
            raise ValueError(f"unknown config keys: {', '.join(sorted(unknown))}")
        for k, v in data.items():
            setattr(cfg, k, v)
        return cfg

    def verify_note(self):
        return ("The target schedule, threshold and penalty are ILLUSTRATIVE "
                "defaults, not the current framework, and this is not legal "
                "advice. Verify " + ", ".join(self.VERIFY_FIELDS)
                + f" against current rules ({MOHRE}, {NAFIS}) before acting on "
                  f"any projection, and use the firm's own time-to-hire.")
