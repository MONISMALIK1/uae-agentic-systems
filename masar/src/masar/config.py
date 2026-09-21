"""Authorities, approval types, cycle times -- and where each one came from.

Every entry in this file encodes how a UAE permitting authority actually
behaves: what an approval requires to already exist before it can be filed,
and how long it typically takes to come back. None of it is a fact of
nature. Authority requirements change by circular, cycle times drift with
workload, and the jurisdictional map is redrawn when a new development zone
is created.

**None of this is regulatory or legal advice.** The dependency graph below
is an illustrative reconstruction of a typical Dubai approval sequence. It
must be verified against each authority's current published requirements,
and against the specific project's jurisdiction, before anyone files or
defers a submission on the strength of it.

The single most important asymmetry, encoded deliberately:

    An UNKNOWN prerequisite is treated as NOT SATISFIED.

Guessing that an unlisted prerequisite is met sends a submission to an
authority that will bounce it, costing a full cycle. Guessing the other way
sends a person to check a document they probably already have. Those errors
are not symmetric, so the defaults are not symmetric either.
"""

import json
from dataclasses import dataclass, asdict, field

DUBAI_MUNICIPALITY = "https://www.dm.gov.ae/"
DEWA = "https://www.dewa.gov.ae/"

# Jurisdictions. Which authority issues the building permit depends on which
# development zone the plot sits in -- this is the thing a planning engineer
# carries in their head and a new hire gets wrong.
JURISDICTIONS = ("dubai_municipality", "trakhees", "dda", "dubai_south")


@dataclass
class Approval:
    """One submission to one authority.

    `requires` names the approval codes that must already be GRANTED before
    this one may be filed. `cycle_days` is the typical authority turnaround
    once filed -- not a promise, a planning figure.
    """
    code: str
    authority: str
    label: str
    requires: tuple = ()
    cycle_days: int = 14
    documents: tuple = ()
    jurisdictions: tuple = JURISDICTIONS     # where this approval applies


@dataclass
class Config:
    # --- the dependency graph ---------------------------------------------
    # VERIFY every row against the authority's current published
    # requirements. Cycle times especially drift.
    approvals: list = field(default_factory=lambda: [
        Approval("AFF", "Dubai Municipality", "Affection plan / site survey",
                 requires=(), cycle_days=5,
                 documents=("title_deed", "site_plan")),

        Approval("CONCEPT", "Authority (by jurisdiction)", "Concept design approval",
                 requires=("AFF",), cycle_days=21,
                 documents=("architectural_drawings", "site_plan")),

        Approval("DCD_DESIGN", "Dubai Civil Defence", "Fire & life-safety design approval",
                 requires=("CONCEPT",), cycle_days=18,
                 documents=("fire_strategy", "architectural_drawings", "mep_drawings")),

        Approval("DEWA_NOC", "DEWA", "Load / substation NOC",
                 requires=("CONCEPT",), cycle_days=25,
                 documents=("load_schedule", "site_plan", "mep_drawings")),

        Approval("SEWER_NOC", "Drainage authority", "Sewerage connection NOC",
                 requires=("CONCEPT",), cycle_days=20,
                 documents=("drainage_drawings", "site_plan")),

        Approval("RTA_NOC", "RTA", "Road / access works NOC",
                 requires=("CONCEPT",), cycle_days=22,
                 documents=("access_drawings", "traffic_impact_study")),

        Approval("TELECOM_NOC", "du / Etisalat", "Telecom infrastructure NOC",
                 requires=("CONCEPT",), cycle_days=15,
                 documents=("mep_drawings",)),

        # The building permit is the convergence point -- it requires every
        # upstream NOC. This is where sequencing errors are most expensive,
        # because a bounce here has already consumed every upstream cycle.
        Approval("BUILDING_PERMIT", "Authority (by jurisdiction)", "Building permit",
                 requires=("DCD_DESIGN", "DEWA_NOC", "SEWER_NOC",
                           "RTA_NOC", "TELECOM_NOC"),
                 cycle_days=30,
                 documents=("structural_drawings", "architectural_drawings",
                            "soil_report", "contractor_licence")),

        Approval("DCD_SITE", "Dubai Civil Defence", "Fire & life-safety site inspection",
                 requires=("BUILDING_PERMIT",), cycle_days=12,
                 documents=("as_built_drawings",)),

        Approval("DEWA_ENERGISE", "DEWA", "Energisation",
                 requires=("BUILDING_PERMIT", "DCD_SITE"), cycle_days=28,
                 documents=("electrical_test_certificates", "as_built_drawings")),

        Approval("COMPLETION", "Authority (by jurisdiction)", "Building completion certificate",
                 requires=("DCD_SITE", "DEWA_ENERGISE"), cycle_days=21,
                 documents=("as_built_drawings", "consultant_completion_letter")),
    ])

    # --- risk appetite -----------------------------------------------------
    # A submission filed this close to a prerequisite's expected grant date
    # is a gamble, not a plan. VERIFY: this is the firm's own tolerance.
    risky_lead_days: int = 5

    # Slip applied to an authority's typical cycle when forecasting a date a
    # person will commit to. A planning figure quoted without contingency
    # gets treated as a promise.
    forecast_contingency_pct: float = 20.0

    sources: dict = field(default_factory=lambda: {
        "approvals": "reconstructed typical Dubai sequence -- VERIFY per authority",
        "cycle_days": "planning figures, drift with authority workload",
        "risky_lead_days": "firm risk appetite, not a published rule",
    })

    VERIFY_FIELDS = ("approvals", "cycle_days", "risky_lead_days")

    def by_code(self, code: str):
        for a in self.approvals:
            if a.code == code:
                return a
        return None

    def applicable(self, jurisdiction: str):
        """Approvals that apply in this jurisdiction, in graph order."""
        return [a for a in self.approvals if jurisdiction in a.jurisdictions]

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
            if k == "approvals":
                cfg.approvals = [Approval(**row) for row in v]
            else:
                setattr(cfg, k, v)
        return cfg

    def verify_note(self):
        return ("The dependency graph and cycle times are an illustrative "
                "reconstruction and change by authority circular. Verify "
                + ", ".join(self.VERIFY_FIELDS)
                + f" against each authority's current requirements "
                  f"({DUBAI_MUNICIPALITY}, {DEWA}) before filing or deferring "
                  f"a submission.")
