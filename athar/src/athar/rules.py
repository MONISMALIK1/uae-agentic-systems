"""All attribution logic lives here, and only here.

This is the deliberate boundary of the whole system. Whether a fine can be
attributed to a person, which assignment covers it, how long is left to
dispute it, and whether the evidence would survive a chargeback are computed
in plain Python from the fine and the custody record. A language model is
never asked to decide any of them -- it is only ever handed the result and
asked to write the account of it.

The reason is unusually sharp here. The output of this pipeline is a document
that names a person and says they incurred a penalty: a recovery notice to a
renter whose card is on file, or an internal note that leads to a
conversation with an employee about money. **A false attribution is not a bad
report. It is an accusation.** It gets a card charged that will be disputed
and lost, or it takes money from someone who was not driving.

So the central design decision of this system is a refusal:

    ATTRIBUTED     exactly one custody interval covers the violation, with
                   margin on both sides of the handover buffer
    CONTESTED      the data cannot settle it -- a handover window, an overlap,
                   or a missing timestamp. NOBODY IS NAMED.
    COMPANY        no custody interval covers it; the vehicle was ours

Every system of this kind that resolves the middle case by guessing produces
a cleaner-looking report and a worse business, because the guesses are
discovered one at a time, expensively, by the person who was wrongly charged.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import assignments as asg_mod
from .config import Config, EMPLOYEE_KINDS

STATE_ORDER = ("CONTESTED", "ATTRIBUTED", "COMPANY", "UNATTRIBUTABLE")
BAND_ORDER = ("urgent", "queue", "monitor")


@dataclass
class Attribution:
    fine_id: str
    plate: str
    state: str
    reasons: list = field(default_factory=list)

    # Only populated when state == ATTRIBUTED. Deliberately empty otherwise.
    assignment_id: str = ""
    driver_id: str = ""
    driver_name: str = ""
    kind: str = ""

    candidates: list = field(default_factory=list)   # assignment ids considered
    amount_aed: float = None
    black_points: int = 0
    days_to_dispute: int = None
    window_days: int = None
    missing_evidence: list = field(default_factory=list)
    recoverable: bool = False
    band: str = "monitor"
    points: int = 0

    @property
    def names_a_person(self) -> bool:
        return bool(self.driver_id or self.driver_name)


@dataclass
class Ledger:
    today: date
    attributions: list = field(default_factory=list)
    data_gaps: list = field(default_factory=list)

    def by_state(self, state):
        return [a for a in self.attributions if a.state == state]

    def actionable(self):
        return [a for a in self.attributions if a.band in ("urgent", "queue")]

    def exposure_aed(self):
        """(recoverable, contested, company) -- money by who can be charged."""
        rec = sum(a.amount_aed or 0.0 for a in self.attributions
                  if a.state == "ATTRIBUTED" and a.recoverable)
        contested = sum(a.amount_aed or 0.0 for a in self.attributions
                        if a.state == "CONTESTED")
        company = sum(a.amount_aed or 0.0 for a in self.attributions
                      if a.state in ("COMPANY", "UNATTRIBUTABLE"))
        return round(rec, 2), round(contested, 2), round(company, 2)

    def facts(self):
        """Every identifier and figure an agent may cite across this run."""
        return {
            "today": self.today.isoformat(),
            "fines": [
                {
                    "fine_id": a.fine_id, "plate": a.plate, "state": a.state,
                    "assignment_id": a.assignment_id,
                    "driver_id": a.driver_id,
                    "amount_aed": a.amount_aed,
                    "days_to_dispute": a.days_to_dispute,
                    "missing_evidence": list(a.missing_evidence),
                    "reasons": list(a.reasons),
                }
                for a in self.actionable()
            ],
        }


def covers(assignment, when: datetime) -> bool:
    """Does this custody interval contain the moment? Open ends are open."""
    if assignment.start_at is None or when is None:
        return False
    if when < assignment.start_at:
        return False
    if assignment.end_at is None:
        return True
    return when <= assignment.end_at


def near_boundary(assignment, when: datetime, buffer_minutes: int) -> bool:
    """Is the moment close enough to a custody boundary to be unsafe?

    Clock skew between an authority's system and a fleet system is real, and
    a vehicle in a handover bay has no clear custodian. A violation inside
    the buffer of either edge cannot be pinned on the person on either side
    of it.
    """
    if assignment.start_at is None or when is None:
        return False
    buf = timedelta(minutes=buffer_minutes)
    if abs(when - assignment.start_at) <= buf:
        return True
    if assignment.end_at is not None and abs(when - assignment.end_at) <= buf:
        return True
    return False


def attribute(fine, plate_assignments, cfg: Config, today: date) -> Attribution:
    """One fine against one vehicle's custody record. No model involved."""
    a = Attribution(fine_id=fine.fine_id, plate=fine.plate, state="CONTESTED",
                    amount_aed=fine.amount_aed, black_points=fine.black_points)

    # --- the dispute clock -------------------------------------------------
    a.window_days = cfg.window_days(fine.source)
    if fine.issued_at is not None:
        a.days_to_dispute = a.window_days - (today - fine.issued_at.date()).days

    # --- can we join at all? -----------------------------------------------
    if fine.issued_at is None:
        a.state = "UNATTRIBUTABLE"
        a.reasons.append("the fine carries no usable timestamp, so it cannot "
                         "be placed against any custody interval")
        return _score(a, cfg)

    usable = [x for x in plate_assignments if x.is_usable]
    if not usable:
        a.state = "COMPANY"
        a.reasons.append(f"no custody record for {fine.plate} at "
                         f"{fine.issued_at.isoformat(sep=' ')} -- the vehicle "
                         f"was in the company's own hands")
        return _score(a, cfg)

    covering = [x for x in usable if covers(x, fine.issued_at)]
    a.candidates = [x.assignment_id for x in covering]

    # --- no interval covers it ---------------------------------------------
    if not covering:
        a.state = "COMPANY"
        a.reasons.append(f"no custody interval contains "
                         f"{fine.issued_at.isoformat(sep=' ')} -- the vehicle "
                         f"was off-hire at the time")
        return _score(a, cfg)

    # --- more than one interval covers it ----------------------------------
    if len(covering) > 1:
        a.state = "CONTESTED"
        a.reasons.append(
            "custody intervals overlap at the moment of the violation ("
            + ", ".join(x.assignment_id for x in covering)
            + ") -- the record contradicts itself and cannot name a driver")
        return _score(a, cfg)

    only = covering[0]

    # --- exactly one, but is it safely inside? -----------------------------
    if near_boundary(only, fine.issued_at, cfg.handover_buffer_minutes):
        a.state = "CONTESTED"
        a.candidates = [only.assignment_id]
        a.reasons.append(
            f"the violation falls within {cfg.handover_buffer_minutes} minutes "
            f"of a custody boundary on {only.assignment_id} -- inside the "
            f"handover window, where the vehicle may have been with either "
            f"party or with neither")
        return _score(a, cfg)

    # --- attributed --------------------------------------------------------
    a.state = "ATTRIBUTED"
    a.assignment_id = only.assignment_id
    a.driver_id = only.driver_id
    a.driver_name = only.driver_name
    a.kind = only.kind
    a.reasons.append(
        f"{only.assignment_id} held the vehicle from "
        f"{only.start_at.isoformat(sep=' ')} to "
        f"{only.end_at.isoformat(sep=' ') if only.end_at else '(open)'}, "
        f"clear of the handover window on both sides")

    # Evidence completeness decides recoverability, not attribution. A fine
    # can be correctly attributed and still be unrecoverable, and conflating
    # the two hides the reason recovery failed.
    if only.kind in EMPLOYEE_KINDS:
        a.recoverable = True
        a.reasons.append(
            "employee assignment -- any recovery from wages is constrained by "
            "UAE labour law and the employment contract; this is a "
            "conversation, not a deduction this tool can authorise")
    else:
        missing = [e for e in cfg.required_rental_evidence
                   if e not in only.evidence_held()]
        a.missing_evidence = missing
        a.recoverable = not missing
        if missing:
            a.reasons.append(
                "attributed, but the evidence bundle is missing "
                + ", ".join(missing)
                + " -- a chargeback on this would likely be lost")

    return _score(a, cfg)


def _score(a: Attribution, cfg: Config) -> Attribution:
    """Priority. Deliberately independent of who is named: a contested fine
    with a closing window is urgent precisely because the evidence has to be
    found before the window shuts."""
    points = 0
    if a.days_to_dispute is not None and 0 < a.days_to_dispute <= cfg.urgent_window_days:
        points += cfg.points["urgent_window"]
        a.reasons.append(f"{a.days_to_dispute} day(s) left of the "
                         f"{a.window_days}-day dispute window")
    if a.amount_aed is not None and a.amount_aed >= cfg.material_amount_aed:
        points += cfg.points["material_amount"]
    if a.black_points:
        points += cfg.points["black_points"]
        a.reasons.append(f"{a.black_points} black point(s) -- a licence "
                         f"consequence, not only money")
    if a.missing_evidence:
        points += cfg.points["incomplete_evidence"]

    a.points = points
    if a.days_to_dispute is not None and a.days_to_dispute <= 0:
        a.band = "monitor"
        a.reasons.append("the dispute window has closed; nothing can be "
                         "contested now")
    elif points >= cfg.urgent_threshold:
        a.band = "urgent"
    elif points >= cfg.queue_threshold:
        a.band = "queue"
    else:
        a.band = "monitor"
    return a


def assess(fine_rows, assignment_rows, cfg: Config, today: date) -> Ledger:
    gaps = [(f.fine_id, note) for f in fine_rows for note in f.parse_notes]
    gaps += [(x.assignment_id, note) for x in assignment_rows
             for note in x.parse_notes]

    grouped = asg_mod.by_plate(assignment_rows)
    fine_plates = {f.plate for f in fine_rows}
    for plate in sorted(set(grouped) - fine_plates):
        gaps.append((plate, f"{len(grouped[plate])} custody record(s) for a "
                            f"plate with no fines this run"))

    attributions = [attribute(f, grouped.get(f.plate, []), cfg, today)
                    for f in fine_rows]
    attributions.sort(key=lambda a: (STATE_ORDER.index(a.state), -a.points,
                                     a.fine_id))
    return Ledger(today=today, attributions=attributions, data_gaps=gaps)
