"""The fines: what an authority says a plate did, and when it reached you."""

import csv
from dataclasses import dataclass, field
from datetime import date, datetime

ALIASES = {
    "fine_id": ("fine_id", "id", "ref", "violation_no"),
    "plate": ("plate", "plate_no", "vehicle", "registration"),
    "issued_at": ("issued_at", "violation_datetime", "occurred_at", "datetime"),
    "received_at": ("received_at", "notified_at", "downloaded_at"),
    "source": ("source", "authority", "issuer"),
    "location": ("location", "place", "road"),
    "amount_aed": ("amount_aed", "amount", "fine_amount", "value"),
    "black_points": ("black_points", "points"),
}


@dataclass
class Fine:
    fine_id: str
    plate: str = ""
    issued_at: datetime = None
    received_at: date = None
    source: str = ""
    location: str = ""
    amount_aed: float = None
    black_points: int = 0
    parse_notes: list = field(default_factory=list)


def _pick(low: dict, key: str, default=""):
    for alias in ALIASES[key]:
        if low.get(alias):
            return low[alias]
    return default


def _parse_datetime(raw: str, notes: list, label: str):
    """A fine without a usable timestamp cannot be joined to anything.

    Returned as None rather than guessed at midnight: a midnight default
    would silently place the violation inside whichever assignment happened
    to span that hour, which is precisely the false attribution this tool
    exists to prevent.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S",
                "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    notes.append(f"{label}: unparseable timestamp '{raw}' -- this fine cannot "
                 f"be attributed to anyone")
    return None


def _parse_date(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_number(raw: str, label: str, notes: list):
    """A malformed amount is a gap, never a zero -- a zero would drop the
    fine below the recovery threshold and out of the queue entirely."""
    raw = (raw or "").strip().replace(",", "").replace("AED", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        notes.append(f"{label}: unparseable amount '{raw}'")
        return None


def load(path: str):
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader, start=1):
            low = {(k or "").strip().lower(): (v or "").strip()
                   for k, v in row.items()}
            fine_id = _pick(low, "fine_id", default=f"FN-{i:05d}")
            plate = _pick(low, "plate").upper().replace(" ", "")
            if not plate:
                continue

            notes = []
            points_raw = _pick(low, "black_points")
            points = 0
            if points_raw:
                try:
                    points = int(float(points_raw))
                except ValueError:
                    notes.append(f"black_points: unparseable '{points_raw}'")

            rows.append(Fine(
                fine_id=fine_id,
                plate=plate,
                issued_at=_parse_datetime(_pick(low, "issued_at"), notes, "issued_at"),
                received_at=_parse_date(_pick(low, "received_at")),
                source=_pick(low, "source").lower(),
                location=_pick(low, "location"),
                amount_aed=_parse_number(_pick(low, "amount_aed"), "amount_aed", notes),
                black_points=points,
                parse_notes=notes,
            ))
    if not rows:
        raise ValueError(
            f"no fines found in {path} -- expected columns named one of "
            f"{ALIASES['fine_id']} and {ALIASES['plate']}")
    return rows
