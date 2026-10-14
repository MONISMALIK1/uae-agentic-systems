"""Terminal report and the review CSV."""

import csv
from collections import Counter

from .rules import STATE_ORDER

MARK = {
    "OVER_ALLOCATED": "!! OVER-ALLOCATED   ",
    "UNDER_ALLOCATED": "!  UNDER-ALLOCATED  ",
    "WITHIN_TOLERANCE": "   within tolerance ",
    "INSUFFICIENT_EVIDENCE": "?  no finding yet   ",
    "NOT_ASSESSABLE": "-- not assessable   ",
}
COLOUR = {
    "OVER_ALLOCATED": "\033[32m", "UNDER_ALLOCATED": "\033[31m",
    "WITHIN_TOLERANCE": "\033[90m", "INSUFFICIENT_EVIDENCE": "\033[33m",
    "NOT_ASSESSABLE": "\033[90m",
}


def terminal(portfolio, cfg, agentic, task=None, use_colour=True):
    L = []
    tint = (lambda s_, t: f"{COLOUR.get(s_, '')}{t}\033[0m") if use_colour \
        else (lambda s_, t: t)

    L.append("")
    L.append("mizan -- district cooling capacity review")
    L.append(f"  as of {portfolio.today.isoformat()}   "
             f"{'reviewed + drafted + gated' if agentic else 'reviewed only'}")
    L.append("")

    counts = Counter(f.state for f in portfolio.findings)
    for state in STATE_ORDER:
        rows = portfolio.by_state(state)
        if not rows:
            continue
        L.append(f"  {state}  ({counts[state]})")
        for f in rows:
            alloc = f"{f.allocated_rt:>7.1f}" if f.allocated_rt is not None else f"{'--':>7}"
            peak = f"{f.observed_peak_rt:>7.1f}" if f.observed_peak_rt is not None else f"{'--':>7}"
            ceiling = (f"{f.recoverable_ceiling_aed:>12,.2f}"
                       if f.recoverable_ceiling_aed else f"{'--':>12}")
            L.append(f"    {tint(state, MARK[state])} {f.unit_id:<10} "
                     f"{f.building[:18]:<20} alloc {alloc} RT  peak {peak} RT  "
                     f"ceiling {ceiling}")
            for r in f.reasons:
                L.append(f"                  - {r}")
        L.append("")

    if portfolio.data_gaps:
        L.append(f"  DATA GAPS  ({len(portfolio.data_gaps)})")
        for ref, note in portfolio.data_gaps[:8]:
            L.append(f"    {ref}: {note}")
        L.append("")

    L.append("  " + "   ".join(f"{counts.get(s, 0)} {s.lower()}"
                               for s in STATE_ORDER if counts.get(s)))
    ceiling = portfolio.total_ceiling_aed()
    L.append(f"  recoverable ceiling across the portfolio: {ceiling:,.2f} AED")
    L.append("  that figure is a CEILING, not a target -- a claim above it "
             "invites the whole case to be dismissed")
    blocked = len(portfolio.by_state("INSUFFICIENT_EVIDENCE"))
    if blocked:
        L.append(f"  {blocked} unit(s) have no finding at all: their evidence "
                 f"window cannot have observed peak demand")
    if task:
        L.append(f"  claim review: {task.get('status', '--')}")
        if task.get("status") == "held":
            L.append(f"    HELD: {task.get('status_reason', '')}")
    L.append("")
    L.append(f"  {cfg.verify_note()}")
    L.append("")
    return "\n".join(L)


FIELDNAMES = ["unit_id", "building", "state", "allocated_rt",
              "observed_peak_rt", "justified_rt", "excess_rt",
              "months_observed", "peak_months_observed", "window",
              "annual_overcharge_aed", "recoverable_ceiling_aed",
              "worth_claiming", "reasons"]


def write_csv(path, portfolio):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        w.writeheader()
        for f in portfolio.findings:
            w.writerow({
                "unit_id": f.unit_id, "building": f.building, "state": f.state,
                "allocated_rt": f.allocated_rt,
                "observed_peak_rt": f.observed_peak_rt,
                "justified_rt": f.justified_rt, "excess_rt": f.excess_rt,
                "months_observed": f.months_observed,
                "peak_months_observed": f.peak_months_observed,
                "window": f.window,
                "annual_overcharge_aed": f.annual_overcharge_aed,
                "recoverable_ceiling_aed": f.recoverable_ceiling_aed,
                "worth_claiming": f.worth_claiming,
                "reasons": " | ".join(f.reasons),
            })
    return path
