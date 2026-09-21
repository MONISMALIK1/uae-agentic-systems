"""All graph logic and all dates live here, and only here.

This is the deliberate boundary of the whole system. Whether a submission is
ready to file, which prerequisite is missing, what the critical path is, and
every forecast date are computed in plain Python from the project state and
the dependency graph. A language model is never asked to decide any of them
-- it is only ever handed the result and asked to write the account of it.

The reason is specific rather than ideological. The output of this pipeline
is advice a planning engineer acts on: *file this now, defer that one, chase
this authority.* A wrong date in that advice does not look wrong. It looks
like a date. It is discovered to be wrong a month later, when the submission
bounces and the upstream cycle has already been consumed -- which is exactly
the failure this system exists to prevent, and would be an embarrassing way
to cause it.

So: every date and every readiness verdict is computed here, and the gate
downstream holds any drafted advice that states a date this file did not
produce or cites an authority reference that is not on the project.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from .config import Config

# Readiness verdicts, most urgent first.
VERDICT_ORDER = ("WILL_BOUNCE", "READY", "RISKY", "BLOCKED", "GRANTED", "FILED")


@dataclass
class Readiness:
    """One approval's state, assessed against the graph. Every field here is
    computed; nothing downstream may add to it."""
    approval_code: str
    label: str
    authority: str
    verdict: str
    reasons: list = field(default_factory=list)
    missing_prerequisites: list = field(default_factory=list)
    missing_documents: list = field(default_factory=list)
    earliest_file_date: date = None      # when prerequisites are expected to clear
    forecast_grant_date: date = None     # earliest_file + cycle + contingency
    reference: str = ""
    is_critical_path: bool = False


@dataclass
class Assessment:
    project_id: str
    project_name: str
    jurisdiction: str
    today: date
    readiness: list = field(default_factory=list)
    critical_path: list = field(default_factory=list)
    forecast_completion: date = None
    data_gaps: list = field(default_factory=list)

    def by_verdict(self, verdict):
        return [r for r in self.readiness if r.verdict == verdict]

    def will_bounce(self):
        return self.by_verdict("WILL_BOUNCE")

    def facts(self):
        """Every reference and every date an agent may cite for this project.

        Two kinds of evidence, because the advice states both: authority
        references it must cite, and computed dates it must not depart from.
        """
        dates = {}
        for r in self.readiness:
            if r.earliest_file_date:
                dates[f"{r.approval_code}_earliest_file"] = r.earliest_file_date.isoformat()
            if r.forecast_grant_date:
                dates[f"{r.approval_code}_forecast_grant"] = r.forecast_grant_date.isoformat()
        if self.forecast_completion:
            dates["forecast_completion"] = self.forecast_completion.isoformat()

        return {
            "project_id": self.project_id,
            "jurisdiction": self.jurisdiction,
            "today": self.today.isoformat(),
            "references": {r.approval_code: r.reference
                           for r in self.readiness if r.reference},
            "dates": dates,
            "critical_path": list(self.critical_path),
            "findings": [
                {"approval": r.approval_code, "verdict": r.verdict,
                 "reasons": list(r.reasons),
                 "missing_prerequisites": list(r.missing_prerequisites),
                 "missing_documents": list(r.missing_documents)}
                for r in self.readiness
                if r.verdict in ("WILL_BOUNCE", "READY", "RISKY", "BLOCKED")
            ],
        }


def _with_contingency(days: int, cfg: Config) -> int:
    """A cycle time quoted without contingency gets treated as a promise."""
    return int(round(days * (1.0 + cfg.forecast_contingency_pct / 100.0)))


def _expected_grant(project, code: str, cfg: Config, today: date,
                    memo: dict) -> date:
    """When this approval is expected to be granted, recursing through
    prerequisites. Returns today for anything already granted.

    Memoised because the graph is a DAG with a convergence point (the
    building permit requires five NOCs), so a naive walk revisits nodes.
    """
    if code in memo:
        return memo[code]

    state = project.state(code)
    if state.is_granted:
        memo[code] = state.granted_on
        return state.granted_on

    approval = cfg.by_code(code)
    if approval is None:
        memo[code] = today
        return today

    # Earliest we could file: once every prerequisite has cleared.
    start = today
    for prereq in approval.requires:
        start = max(start, _expected_grant(project, prereq, cfg, today, memo))

    # If it is already filed, the clock started when it was filed.
    if state.status == "filed" and state.filed_on:
        start = state.filed_on

    result = start + timedelta(days=_with_contingency(approval.cycle_days, cfg))
    memo[code] = result
    return result


def assess_approval(project, approval, cfg: Config, today: date,
                    memo: dict) -> Readiness:
    """One approval against the project's current state. No model involved."""
    state = project.state(approval.code)
    r = Readiness(
        approval_code=approval.code, label=approval.label,
        authority=approval.authority, verdict="BLOCKED",
        reference=state.reference,
    )

    # --- already resolved --------------------------------------------------
    if state.is_granted:
        r.verdict = "GRANTED"
        r.reasons.append(f"granted {state.granted_on.isoformat()}")
        return r

    # --- what is missing ---------------------------------------------------
    missing_prereqs = [p for p in approval.requires
                       if not project.state(p).is_granted]
    r.missing_prerequisites = missing_prereqs

    held = {d.lower() for d in state.documents_held}
    missing_docs = [d for d in approval.documents if d.lower() not in held]
    r.missing_documents = missing_docs

    # --- already filed: the interesting case -------------------------------
    # A submission that is ALREADY with the authority but was filed without
    # its prerequisites in place is the expensive failure this tool exists
    # for. It is not "pending" -- it is going to bounce, and the person needs
    # to know now rather than in three weeks.
    if state.status == "filed":
        if missing_prereqs:
            r.verdict = "WILL_BOUNCE"
            r.reasons.append(
                f"filed {state.filed_on.isoformat() if state.filed_on else '(no date)'} "
                f"but {len(missing_prereqs)} prerequisite(s) are not granted: "
                + ", ".join(missing_prereqs))
            r.reasons.append("the authority will reject on sequence, and the "
                             "cycle already spent is lost")
        else:
            r.verdict = "FILED"
            r.reasons.append(
                f"with the authority since "
                f"{state.filed_on.isoformat() if state.filed_on else '(no date)'}")
        return r

    if state.status == "rejected":
        r.verdict = "READY" if not missing_prereqs and not missing_docs else "BLOCKED"
        r.reasons.append("previously rejected -- resubmission required")

    # --- not yet filed -----------------------------------------------------
    if missing_prereqs:
        r.verdict = "BLOCKED"
        r.reasons.append("waiting on " + ", ".join(missing_prereqs))
        earliest = today
        for p in missing_prereqs:
            earliest = max(earliest, _expected_grant(project, p, cfg, today, memo))
        r.earliest_file_date = earliest

        # Filing very close to a prerequisite's expected grant is a gamble.
        lead = (earliest - today).days
        if 0 < lead <= cfg.risky_lead_days:
            r.verdict = "RISKY"
            r.reasons.append(
                f"prerequisite expected to clear in {lead} day(s) -- inside the "
                f"{cfg.risky_lead_days}-day caution window, so filing now is a "
                f"gamble on the authority being on time")
    else:
        r.earliest_file_date = today
        if missing_docs:
            r.verdict = "BLOCKED"
            r.reasons.append("prerequisites are clear but documents are missing: "
                             + ", ".join(missing_docs))
        else:
            r.verdict = "READY"
            r.reasons.append("every prerequisite granted and every document held")

    if r.earliest_file_date:
        r.forecast_grant_date = r.earliest_file_date + timedelta(
            days=_with_contingency(approval.cycle_days, cfg))
    return r


def critical_path(project, cfg: Config, today: date, memo: dict):
    """The chain of not-yet-granted approvals that determines completion.

    Walked backwards from the terminal approval, at each step taking the
    prerequisite with the latest expected grant date -- that is the one
    actually setting the schedule.
    """
    applicable = cfg.applicable(project.jurisdiction)
    if not applicable:
        return []
    terminal = applicable[-1].code

    path = []
    code = terminal
    seen = set()
    while code and code not in seen:
        seen.add(code)
        if not project.state(code).is_granted:
            path.append(code)
        approval = cfg.by_code(code)
        if not approval or not approval.requires:
            break
        pending = [p for p in approval.requires
                   if not project.state(p).is_granted]
        if not pending:
            break
        code = max(pending,
                   key=lambda p: _expected_grant(project, p, cfg, today, memo))
    return list(reversed(path))


def assess(project, cfg: Config, today: date) -> Assessment:
    memo: dict = {}
    applicable = cfg.applicable(project.jurisdiction)

    gaps = list(project.parse_notes)
    for code, state in project.states.items():
        for note in state.parse_notes:
            gaps.append(f"{code}: {note}")
        if cfg.by_code(code) is None:
            gaps.append(f"{code}: not in the configured approval graph -- "
                        f"ignored in sequencing")

    readiness = [assess_approval(project, a, cfg, today, memo)
                 for a in applicable]

    path = critical_path(project, cfg, today, memo)
    for r in readiness:
        r.is_critical_path = r.approval_code in path

    completion = None
    if applicable:
        completion = _expected_grant(project, applicable[-1].code, cfg, today, memo)

    readiness.sort(key=lambda r: (VERDICT_ORDER.index(r.verdict),
                                  r.approval_code))

    return Assessment(
        project_id=project.project_id, project_name=project.project_name,
        jurisdiction=project.jurisdiction, today=today,
        readiness=readiness, critical_path=path,
        forecast_completion=completion, data_gaps=gaps,
    )
