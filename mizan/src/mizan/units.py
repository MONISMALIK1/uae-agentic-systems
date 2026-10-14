"""The allocation on record, and the consumption actually metered."""

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

UNIT_ALIASES = {
    "unit_id": ("unit_id", "id", "ref", "premise_no"),
    "building": ("building", "tower", "development"),
    "unit_type": ("unit_type", "type", "use", "category"),
    "allocated_rt": ("allocated_rt", "capacity_rt", "contracted_rt", "rt"),
    "rate_aed_per_rt_year": ("rate_aed_per_rt_year", "capacity_rate",
                             "rt_rate", "tariff"),
    "owner_ref": ("owner_ref", "owner", "account_ref"),
}

READING_ALIASES = {
    "unit_id": ("unit_id", "id", "ref", "premise_no"),
    "month": ("month", "period", "billing_month"),
    "peak_demand_rt": ("peak_demand_rt", "peak_rt", "max_demand"),
    "consumption_rt_hours": ("consumption_rt_hours", "rt_hours", "consumption"),
}


@dataclass
class Unit:
    unit_id: str
    building: str = ""
    unit_type: str = ""
    allocated_rt: float = None
    rate_aed_per_rt_year: float = None
    owner_ref: str = ""
    parse_notes: list = field(default_factory=list)

    @property
    def is_assessable(self) -> bool:
        """An allocation and a rate are both needed. A missing allocation is
        not zero -- zero would compute a nonsensical over-allocation of the
        entire charge."""
        return (self.allocated_rt is not None and self.allocated_rt > 0
                and self.rate_aed_per_rt_year is not None)


@dataclass
class Reading:
    unit_id: str
    month: str = ""            # YYYY-MM
    peak_demand_rt: float = None
    consumption_rt_hours: float = None
    parse_notes: list = field(default_factory=list)

    @property
    def month_number(self):
        try:
            return int(self.month.split("-")[1])
        except (IndexError, ValueError):
            return None

    @property
    def is_usable(self) -> bool:
        """A reading without a peak figure cannot speak to capacity.

        Consumption (RT-hours) measures how much cooling was used over the
        month; the capacity charge is sized on the highest instantaneous
        draw. A month of heavy but flat usage and a month with one brief
        spike can have identical RT-hours and very different peaks, so
        consumption cannot stand in for the peak figure.
        """
        return self.month_number is not None and self.peak_demand_rt is not None


def _pick(low: dict, aliases: dict, key: str, default=""):
    for alias in aliases[key]:
        if low.get(alias):
            return low[alias]
    return default


def _parse_float(raw: str, label: str, notes: list):
    """A malformed figure is a gap, never a zero."""
    raw = (raw or "").strip().replace(",", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        notes.append(f"{label}: unparseable figure '{raw}'")
        return None


def _normalise_month(raw: str, notes: list):
    raw = (raw or "").strip()
    if not raw:
        return ""
    for fmt in ("%Y-%m", "%m/%Y", "%b-%Y", "%B %Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m")
        except ValueError:
            continue
    notes.append(f"month: unparseable period '{raw}' -- this reading cannot "
                 f"be placed in a season")
    return ""


def load_units(path: str):
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            low = {(k or "").strip().lower(): (v or "").strip()
                   for k, v in row.items()}
            unit_id = _pick(low, UNIT_ALIASES, "unit_id")
            if not unit_id:
                continue
            notes = []
            rows.append(Unit(
                unit_id=unit_id,
                building=_pick(low, UNIT_ALIASES, "building"),
                unit_type=_pick(low, UNIT_ALIASES, "unit_type").lower(),
                allocated_rt=_parse_float(
                    _pick(low, UNIT_ALIASES, "allocated_rt"), "allocated_rt", notes),
                rate_aed_per_rt_year=_parse_float(
                    _pick(low, UNIT_ALIASES, "rate_aed_per_rt_year"),
                    "rate_aed_per_rt_year", notes),
                owner_ref=_pick(low, UNIT_ALIASES, "owner_ref"),
                parse_notes=notes,
            ))
    if not rows:
        raise ValueError(
            f"no units found in {path} -- expected a column named one of "
            f"{UNIT_ALIASES['unit_id']}")
    return rows


def load_readings(path: str):
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            low = {(k or "").strip().lower(): (v or "").strip()
                   for k, v in row.items()}
            unit_id = _pick(low, READING_ALIASES, "unit_id")
            if not unit_id:
                continue
            notes = []
            rows.append(Reading(
                unit_id=unit_id,
                month=_normalise_month(
                    _pick(low, READING_ALIASES, "month"), notes),
                peak_demand_rt=_parse_float(
                    _pick(low, READING_ALIASES, "peak_demand_rt"),
                    "peak_demand_rt", notes),
                consumption_rt_hours=_parse_float(
                    _pick(low, READING_ALIASES, "consumption_rt_hours"),
                    "consumption_rt_hours", notes),
                parse_notes=notes,
            ))
    return rows


def by_unit(readings):
    grouped = defaultdict(list)
    for r in readings:
        grouped[r.unit_id].append(r)
    for unit_id in grouped:
        grouped[unit_id].sort(key=lambda r: r.month)
    return grouped
