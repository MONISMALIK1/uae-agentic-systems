"""Windows, buffers and thresholds -- and where each one came from.

Every number in this file is a commercial or legal parameter, not a fact of
nature. Dispute windows differ by issuing authority and change; handover
buffers are a firm's own estimate of how sloppy its own timestamps are; and
what may lawfully be deducted from an employee's wages is a question of UAE
labour law, not of this tool.

**None of these defaults are legal advice.** Confirm every window against the
issuing authority's current rules, and confirm any wage-deduction action
against UAE labour law and the employment contract, before acting on an
attribution.

The asymmetry that runs through the whole file:

    When the data cannot establish who was driving, the answer is
    "we do not know" -- never a name.

An attribution asserted and then overturned is worse than no attribution: it
means a chargeback lost on evidence, or a deduction taken from the wrong
person's salary. So every threshold below is tuned to widen the contested
band rather than narrow it.
"""

import json
from dataclasses import dataclass, asdict, field

DUBAI_POLICE = "https://www.dubaipolice.gov.ae/"
RTA = "https://www.rta.ae/"

# Assignment kinds. The distinction matters downstream: a rental attribution
# leads to a card charge, an employee attribution leads to a conversation
# constrained by labour law. They are not the same action.
RENTAL_KINDS = ("rental",)
EMPLOYEE_KINDS = ("shift", "pool")


@dataclass
class Config:
    # --- the handover buffer ------------------------------------------------
    # A fine issued this close to an assignment boundary is CONTESTED, not
    # attributed. Clock skew between an authority's system and a rental
    # system is real, and a vehicle sitting in a handover bay has no clear
    # custodian. VERIFY: this is the firm's own estimate of its timestamp
    # discipline -- measure it before trusting the default.
    handover_buffer_minutes: int = 45

    # --- dispute windows ----------------------------------------------------
    # Days from the fine's issue date within which a challenge must reach the
    # issuing authority. VERIFY every row: these differ by authority and
    # change. An unknown source falls back to the shortest window, because
    # assuming a generous deadline is how a contestable fine goes
    # uncontested.
    dispute_window_days: dict = field(default_factory=lambda: {
        "dubai_police": 30,
        "abu_dhabi_police": 30,
        "sharjah_police": 30,
        "rta_salik": 15,
        "parking": 15,
    })
    default_dispute_window_days: int = 15

    # A window closing inside this many days is urgent -- an evidence bundle
    # that is not assembled by then is not going to be.
    urgent_window_days: int = 5

    # --- recovery -----------------------------------------------------------
    # Below this, chasing costs more than the fine. VERIFY: the firm's own
    # cost-to-collect, which is mostly a labour figure.
    min_recoverable_aed: float = 50.0

    # Evidence a rental attribution needs to survive a card chargeback. A
    # bundle missing any of these is attributed but not recoverable, and the
    # report says which.
    required_rental_evidence: tuple = ("contract_ref", "handover_doc")

    # --- scoring ------------------------------------------------------------
    points: dict = field(default_factory=lambda: {
        "urgent_window": 40,
        "material_amount": 25,
        "black_points": 30,       # a licence consequence, not just money
        "incomplete_evidence": 15,
    })
    material_amount_aed: float = 1000.0

    urgent_threshold: int = 55
    queue_threshold: int = 25

    sources: dict = field(default_factory=lambda: {
        "dispute_window_days": "issuing authority rules -- VERIFY, they differ and change",
        "handover_buffer_minutes": "firm's own timestamp discipline, measure it",
        "min_recoverable_aed": "firm's cost-to-collect",
    })

    VERIFY_FIELDS = ("dispute_window_days", "handover_buffer_minutes",
                     "min_recoverable_aed")

    def window_days(self, source: str) -> int:
        """Dispute window for an issuing source, defaulting short.

        An unrecognised source gets the shortest configured window rather
        than a generous one: assuming a long deadline is how a contestable
        fine quietly goes uncontested.
        """
        return self.dispute_window_days.get(
            (source or "").strip().lower(), self.default_dispute_window_days)

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
        return ("Dispute windows differ by issuing authority and change; the "
                "handover buffer is a firm-specific estimate. Verify "
                + ", ".join(self.VERIFY_FIELDS)
                + f" against the authority's current rules ({DUBAI_POLICE}, "
                  f"{RTA}) and confirm any wage deduction against UAE labour "
                  f"law before acting on an attribution.")
