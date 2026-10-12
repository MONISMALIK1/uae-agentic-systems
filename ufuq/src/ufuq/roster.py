"""Where a company stands today, and what it says is coming."""

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

ROSTER_ALIASES = {
    "company_id": ("company_id", "id", "ref", "establishment_no"),
    "company_name": ("company_name", "name", "company", "establishment"),
    "as_of": ("as_of", "date", "snapshot_date"),
    "skilled_roles": ("skilled_roles", "total_skilled", "skilled_headcount"),
    "emirati_skilled": ("emirati_skilled", "emirati_count", "nationals_skilled"),
}

PIPELINE_ALIASES = {
    "company_id": ("company_id", "id", "ref", "establishment_no"),
    "event_id": ("event_id", "id", "requisition_ref", "ref"),
    "event_type": ("event_type", "type", "kind"),
    "stage": ("stage", "status", "confidence"),
    "is_emirati": ("is_emirati", "emirati", "national"),
    "is_skilled": ("is_skilled", "skilled"),
    "expected_date": ("expected_date", "start_date", "effective_date"),
}

EVENT_TYPES = {"hire", "exit"}
TRUTHY = {"y", "yes", "true", "1"}


@dataclass
class Snapshot:
    company_id: str
    company_name: str = ""
    as_of: date = None
    skilled_roles: int = None
    emirati_skilled: int = None
    parse_notes: list = field(default_factory=list)

    @property
    def is_projectable(self) -> bool:
        """Both counts and a date are needed. A missing count is not a zero:
        reporting zero Emirati staff for a company whose file was incomplete
        manufactures a breach that does not exist."""
        return (self.as_of is not None
                and self.skilled_roles is not None
                and self.emirati_skilled is not None)


@dataclass
class Event:
    company_id: str
    event_id: str
    event_type: str = "hire"
    stage: str = "sourcing"
    is_emirati: bool = False
    is_skilled: bool = True
    expected_date: date = None
    parse_notes: list = field(default_factory=list)


def _pick(low: dict, aliases: dict, key: str, default=""):
    for alias in aliases[key]:
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


def _parse_int(raw: str, label: str, notes: list):
    """A malformed count is a gap, never a zero.

    Zero Emirati staff is a breach; an unreadable figure is an unknown. They
    must not produce the same report.
    """
    raw = (raw or "").strip().replace(",", "")
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        notes.append(f"{label}: unparseable count '{raw}'")
        return None


def load_roster(path: str):
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            low = {(k or "").strip().lower(): (v or "").strip()
                   for k, v in row.items()}
            company_id = _pick(low, ROSTER_ALIASES, "company_id")
            if not company_id:
                continue

            notes = []
            as_of, err = _parse_date(_pick(low, ROSTER_ALIASES, "as_of"))
            if err:
                notes.append(f"as_of: {err}")

            skilled = _parse_int(_pick(low, ROSTER_ALIASES, "skilled_roles"),
                                 "skilled_roles", notes)
            emirati = _parse_int(_pick(low, ROSTER_ALIASES, "emirati_skilled"),
                                 "emirati_skilled", notes)

            if (skilled is not None and emirati is not None
                    and emirati > skilled):
                notes.append(f"emirati_skilled ({emirati}) exceeds "
                             f"skilled_roles ({skilled}) -- the snapshot "
                             f"contradicts itself and cannot be projected")
                skilled = emirati = None

            rows.append(Snapshot(
                company_id=company_id,
                company_name=_pick(low, ROSTER_ALIASES, "company_name"),
                as_of=as_of, skilled_roles=skilled, emirati_skilled=emirati,
                parse_notes=notes,
            ))
    if not rows:
        raise ValueError(
            f"no roster rows found in {path} -- expected a column named one "
            f"of {ROSTER_ALIASES['company_id']}")
    return rows


def load_pipeline(path: str):
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader, start=1):
            low = {(k or "").strip().lower(): (v or "").strip()
                   for k, v in row.items()}
            company_id = _pick(low, PIPELINE_ALIASES, "company_id")
            if not company_id:
                continue

            notes = []
            event_type = (_pick(low, PIPELINE_ALIASES, "event_type")
                          or "hire").lower()
            if event_type not in EVENT_TYPES:
                notes.append(f"event_type: unrecognised '{event_type}', "
                             f"treated as a hire")
                event_type = "hire"

            stage = (_pick(low, PIPELINE_ALIASES, "stage") or "sourcing").lower()

            expected, err = _parse_date(
                _pick(low, PIPELINE_ALIASES, "expected_date"))
            if err:
                notes.append(f"expected_date: {err} -- this event cannot be "
                             f"placed on the timeline")

            rows.append(Event(
                company_id=company_id,
                event_id=_pick(low, PIPELINE_ALIASES, "event_id",
                               default=f"REQ-{i:05d}"),
                event_type=event_type,
                stage=stage,
                is_emirati=_pick(low, PIPELINE_ALIASES, "is_emirati").lower() in TRUTHY,
                is_skilled=(_pick(low, PIPELINE_ALIASES, "is_skilled").lower()
                            in TRUTHY) or not _pick(low, PIPELINE_ALIASES, "is_skilled"),
                expected_date=expected,
                parse_notes=notes,
            ))
    return rows


def by_company(events):
    grouped = defaultdict(list)
    for e in events:
        grouped[e.company_id].append(e)
    return grouped
