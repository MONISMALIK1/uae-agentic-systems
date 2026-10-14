"""Tolerances, tariffs and evidence standards -- and where each came from.

**None of these figures are tariff, legal or engineering advice.** District
cooling tariffs are set per provider and per scheme and are regulated; the
headroom factor below is a plant-sizing judgement, not a rule; and the
limitation period for a billing claim is a legal question. Every figure here
is an illustrative default that exists to exercise the arithmetic. Verify all
of them before putting a claim in front of a provider or a regulator.

The asymmetry this file encodes, and the reason the system exists:

    An allocation can only be challenged on evidence that could actually
    have observed the peak.

A unit's capacity charge is levied on allocated refrigeration tons, and the
allocation is meant to cover peak demand. Peak demand in this climate happens
in high summer. **A dataset that does not span a summer cannot establish that
a unit is over-allocated** -- it can only establish that the unit was not
working hard in winter, which is not a finding.

Claiming on that evidence would be overclaiming, and overclaiming against a
regulated utility is how a legitimate case gets dismissed and not re-heard.
So insufficient evidence is a hard stop here, not a weak finding.
"""

import json
from dataclasses import dataclass, asdict, field

RSB_DUBAI = "https://www.rsbdubai.gov.ae/"

# Months when cooling demand peaks in this climate. An evidence window that
# misses these has not seen the thing the allocation is sized for.
PEAK_MONTHS = (6, 7, 8, 9)


@dataclass
class Config:
    # --- evidence standard --------------------------------------------------
    # Minimum months of consumption before an allocation may be challenged.
    # VERIFY: this is a defensibility judgement, not a published rule.
    min_months_evidence: int = 12

    # And at least this many of them must be peak-season months. One hot
    # month is an anecdote; two is a pattern that survives questioning.
    min_peak_months: int = 2

    # --- what justifies an allocation --------------------------------------
    # Observed peak demand, plus headroom. Plant is legitimately sized above
    # the highest observed draw -- for diversity, for a hotter year, for
    # equipment ageing. Claiming down to exactly observed peak would be
    # engineering nonsense and would lose.
    # VERIFY: a mechanical engineer's number, not a billing one.
    headroom_factor: float = 1.15

    # An allocation within this multiple of the justified figure is not worth
    # challenging -- the claim costs more than it returns and invites a
    # fight over methodology.
    tolerance_factor: float = 1.25

    # --- money --------------------------------------------------------------
    # Years of past charges a claim may reasonably reach back over.
    # VERIFY: this is a legal question about limitation periods and about the
    # provider's own billing terms. It is NOT advice.
    claimable_years: int = 3

    # Below this, the recovery does not justify the dispute effort.
    min_claim_aed: float = 2000.0

    # --- banding ------------------------------------------------------------
    material_claim_aed: float = 20000.0

    sources: dict = field(default_factory=lambda: {
        "headroom_factor": "plant-sizing judgement -- confirm with an MEP engineer",
        "claimable_years": "limitation period and provider billing terms -- legal question",
        "min_months_evidence": "defensibility judgement, not a published rule",
        "tolerance_factor": "claim economics, firm-specific",
    })

    VERIFY_FIELDS = ("headroom_factor", "claimable_years",
                     "min_months_evidence", "tolerance_factor")

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
        return ("Headroom, limitation period and evidence standards are "
                "illustrative defaults, not tariff, legal or engineering "
                "advice. Verify " + ", ".join(self.VERIFY_FIELDS)
                + f" with an MEP engineer and against the provider's billing "
                  f"terms and the regulator ({RSB_DUBAI}) before submitting "
                  f"any claim.")
