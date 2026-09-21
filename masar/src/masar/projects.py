"""Project state: which approvals are granted, filed, or not yet started."""

import csv
from dataclasses import dataclass, field
from datetime import date, datetime

ALIASES = {
    "project_id": ("project_id", "id", "ref", "job_no"),
    "project_name": ("project_name", "name", "project"),
    "jurisdiction": ("jurisdiction", "authority_zone", "zone"),
    "approval_code": ("approval_code", "approval", "code", "stage"),
    "status": ("status", "state"),
    "filed_on": ("filed_on", "submitted_on", "date_filed"),
    "granted_on": ("granted_on", "approved_on", "date_granted"),
    "documents_held": ("documents_held", "documents", "docs"),
    "reference": ("reference", "ref_no", "authority_ref", "permit_no"),
}

# A status the loader does not recognise is NOT treated as granted. See the
# asymmetry note in config.py -- unknown means not satisfied.
KNOWN_STATUSES = {"not_started", "preparing", "filed", "granted", "rejected"}


@dataclass
class ApprovalState:
    project_id: str
    approval_code: str
    status: str = "not_started"
    filed_on: date = None
    granted_on: date = None
    documents_held: list = field(default_factory=list)
    reference: str = ""
    parse_notes: list = field(default_factory=list)

    @property
    def is_granted(self) -> bool:
        """Granted requires BOTH the status and a date. A row marked granted
        with no grant date is an assertion nobody can check, and this tool
        does not let an unverifiable assertion unblock a downstream filing."""
        return self.status == "granted" and self.granted_on is not None


@dataclass
class Project:
    project_id: str
    project_name: str = ""
    jurisdiction: str = "dubai_municipality"
    states: dict = field(default_factory=dict)   # approval_code -> ApprovalState
    parse_notes: list = field(default_factory=list)

    def state(self, code: str) -> ApprovalState:
        return self.states.get(
            code, ApprovalState(self.project_id, code, status="not_started"))


def _pick(low: dict, key: str, default=""):
    for alias in ALIASES[key]:
        if low.get(alias):
            return low[alias]
    return default


def _parse_date(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return None, None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date(), None
        except ValueError:
            continue
    return None, f"unparseable date '{raw}'"


def load(path: str):
    """One row per (project, approval). Projects are assembled from rows."""
    projects: dict = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader, start=1):
            low = {(k or "").strip().lower(): (v or "").strip()
                   for k, v in row.items()}
            project_id = _pick(low, "project_id")
            code = _pick(low, "approval_code").upper()
            if not project_id or not code:
                continue

            notes = []
            status = (_pick(low, "status") or "not_started").lower()
            if status not in KNOWN_STATUSES:
                notes.append(f"status: unrecognised '{status}', treated as "
                             f"not_started -- an unknown status never unblocks "
                             f"a downstream filing")
                status = "not_started"

            filed, err = _parse_date(_pick(low, "filed_on"))
            if err:
                notes.append(f"filed_on: {err}")
            granted, err = _parse_date(_pick(low, "granted_on"))
            if err:
                notes.append(f"granted_on: {err}")

            if status == "granted" and granted is None:
                notes.append("marked granted with no grant date -- not treated "
                             "as granted, because nothing can verify it")

            docs = [d.strip() for d in _pick(low, "documents_held").replace(",", ";").split(";")
                    if d.strip()]

            if project_id not in projects:
                projects[project_id] = Project(
                    project_id=project_id,
                    project_name=_pick(low, "project_name"),
                    jurisdiction=(_pick(low, "jurisdiction")
                                  or "dubai_municipality").lower(),
                )
            p = projects[project_id]
            if not p.project_name:
                p.project_name = _pick(low, "project_name")

            p.states[code] = ApprovalState(
                project_id=project_id, approval_code=code, status=status,
                filed_on=filed, granted_on=granted, documents_held=docs,
                reference=_pick(low, "reference"), parse_notes=notes,
            )

    if not projects:
        raise ValueError(
            f"no project rows found in {path} -- expected columns named one of "
            f"{ALIASES['project_id']} and {ALIASES['approval_code']}")
    return list(projects.values())
