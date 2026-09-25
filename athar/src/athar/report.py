"""Terminal report and the attribution CSV."""

import csv
from collections import Counter

from .rules import STATE_ORDER

MARK = {
    "CONTESTED": "?? CONTESTED ",
    "ATTRIBUTED": "   attributed",
    "COMPANY": "   company   ",
    "UNATTRIBUTABLE": "!! no join   ",
}
COLOUR = {"CONTESTED": "\033[33m", "ATTRIBUTED": "\033[32m",
          "COMPANY": "\033[90m", "UNATTRIBUTABLE": "\033[31m"}

# What the report prints where a driver would go, when the engine declined to
# establish one. Deliberately a sentence rather than a blank: a blank column
# invites someone to fill it in.
NOT_ESTABLISHED = "-- not established --"


def terminal(ledger, cfg, agentic, task=None, use_colour=True, show_all=False):
    L = []
    tint = (lambda s_, t: f"{COLOUR.get(s_, '')}{t}\033[0m") if use_colour \
        else (lambda s_, t: t)

    L.append("")
    L.append("athar -- fleet fine attribution")
    L.append(f"  as of {ledger.today.isoformat()}   "
             f"{'attributed + drafted + gated' if agentic else 'attributed only'}")
    L.append("")

    counts = Counter(a.state for a in ledger.attributions)
    for state in STATE_ORDER:
        rows = ledger.by_state(state)
        if not rows:
            continue
        shown = rows if show_all else [r for r in rows
                                       if r.band in ("urgent", "queue")]
        L.append(f"  {state}  ({counts[state]})")
        if not shown:
            L.append(f"    (none in an actionable band; --show-all to list)")
        for a in shown:
            amount = (f"{a.amount_aed:>9,.2f}" if a.amount_aed is not None
                      else f"{'--':>9}")
            left = (f"{a.days_to_dispute:>3}d" if a.days_to_dispute is not None
                    else " --")
            who = a.driver_id or (NOT_ESTABLISHED
                                  if a.state == "CONTESTED" else "--")
            L.append(f"    {tint(state, MARK[state])} {a.fine_id:<10} "
                     f"{a.plate:<10} AED {amount}  left {left}  "
                     f"pts {a.points:>3}  {who}")
            for r in a.reasons:
                L.append(f"                  - {r}")
        L.append("")

    if ledger.data_gaps:
        L.append(f"  DATA GAPS  ({len(ledger.data_gaps)})")
        for ref, note in ledger.data_gaps[:8]:
            L.append(f"    {ref}: {note}")
        if len(ledger.data_gaps) > 8:
            L.append(f"    ... and {len(ledger.data_gaps) - 8} more")
        L.append("")

    rec, contested, company = ledger.exposure_aed()
    L.append("  " + "   ".join(f"{counts.get(s, 0)} {s.lower()}"
                               for s in STATE_ORDER))
    L.append(f"  recoverable {rec:,.2f} AED   contested {contested:,.2f} AED"
             f"   company-borne {company:,.2f} AED")
    if contested:
        L.append(f"  the contested figure is the cost of timestamp discipline, "
                 f"not of bad drivers")
    if task:
        L.append(f"  advice review: {task.get('status', '--')}")
        if task.get("status") == "held":
            L.append(f"    HELD: {task.get('status_reason', '')}")
        elif task.get("status") == "released":
            L.append(f"    {task.get('notice', '')[:110]}")
    L.append("")
    L.append(f"  {cfg.verify_note()}")
    L.append("")
    return "\n".join(L)


FIELDNAMES = ["fine_id", "plate", "state", "band", "points", "amount_aed",
              "black_points", "days_to_dispute", "window_days",
              "assignment_id", "driver_id", "driver_name", "kind",
              "candidates", "missing_evidence", "recoverable", "reasons"]


def write_csv(path, ledger):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        w.writeheader()
        for a in ledger.attributions:
            w.writerow({
                "fine_id": a.fine_id, "plate": a.plate, "state": a.state,
                "band": a.band, "points": a.points,
                "amount_aed": a.amount_aed, "black_points": a.black_points,
                "days_to_dispute": a.days_to_dispute,
                "window_days": a.window_days,
                "assignment_id": a.assignment_id, "driver_id": a.driver_id,
                "driver_name": a.driver_name, "kind": a.kind,
                "candidates": ";".join(a.candidates),
                "missing_evidence": ";".join(a.missing_evidence),
                "recoverable": a.recoverable,
                "reasons": " | ".join(a.reasons),
            })
    return path
