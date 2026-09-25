"""Custody: who had which vehicle, between which two moments.

An assignment is a claim about custody, and the evidence attached to it is
what makes that claim survive a dispute. A rental contract with no signed
handover document establishes that someone rented a car; it does not
establish what time they collected it, which is the fact a chargeback turns
on.
"""

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

ALIASES = {
    "assignment_id": ("assignment_id", "id", "ref"),
    "plate": ("plate", "plate_no", "vehicle", "registration"),
    "driver_id": ("driver_id", "renter_id", "employee_id"),
    "driver_name": ("driver_name", "renter_name", "employee_name", "name"),
    "kind": ("kind", "type", "assignment_type"),
    "start_at": ("start_at", "from", "collected_at", "shift_start"),
    "end_at": ("end_at", "to", "returned_at", "shift_end"),
    "contract_ref": ("contract_ref", "contract", "agreement_no"),
    "handover_doc": ("handover_doc", "handover", "condition_report"),
}

KNOWN_KINDS = {"rental", "shift", "pool"}


@dataclass
class Assignment:
    assignment_id: str
    plate: str = ""
    driver_id: str = ""
    driver_name: str = ""
    kind: str = "rental"
    start_at: datetime = None
    end_at: datetime = None
    contract_ref: str = ""
    handover_doc: str = ""
    parse_notes: list = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        """An assignment with no start is not a custody claim at all.

        An open end (a rental not yet returned, a shift still running) IS
        usable -- it is handled as an open interval downstream.
        """
        return self.start_at is not None

    def evidence_held(self):
        held = set()
        if self.contract_ref:
            held.add("contract_ref")
        if self.handover_doc:
            held.add("handover_doc")
        return held


def _pick(low: dict, key: str, default=""):
    for alias in ALIASES[key]:
        if low.get(alias):
            return low[alias]
    return default


def _parse_datetime(raw: str, notes: list, label: str):
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S",
                "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    notes.append(f"{label}: unparseable timestamp '{raw}'")
    return None


def load(path: str):
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader, start=1):
            low = {(k or "").strip().lower(): (v or "").strip()
                   for k, v in row.items()}
            plate = _pick(low, "plate").upper().replace(" ", "")
            if not plate:
                continue

            notes = []
            kind = (_pick(low, "kind") or "rental").lower()
            if kind not in KNOWN_KINDS:
                notes.append(f"kind: unrecognised '{kind}', treated as rental "
                             f"-- verify before any wage deduction, which is "
                             f"constrained differently")
                kind = "rental"

            start = _parse_datetime(_pick(low, "start_at"), notes, "start_at")
            end = _parse_datetime(_pick(low, "end_at"), notes, "end_at")
            if start and end and end < start:
                notes.append("end_at precedes start_at -- interval discarded")
                start = end = None

            rows.append(Assignment(
                assignment_id=_pick(low, "assignment_id", default=f"ASG-{i:05d}"),
                plate=plate,
                driver_id=_pick(low, "driver_id"),
                driver_name=_pick(low, "driver_name"),
                kind=kind,
                start_at=start,
                end_at=end,
                contract_ref=_pick(low, "contract_ref"),
                handover_doc=_pick(low, "handover_doc"),
                parse_notes=notes,
            ))
    return rows


def by_plate(assignments):
    grouped = defaultdict(list)
    for a in assignments:
        grouped[a.plate].append(a)
    for plate in grouped:
        grouped[plate].sort(key=lambda a: (a.start_at or datetime.min))
    return grouped
