"""Terminal report and the projection CSV.

**This module carries a safety responsibility, not just a presentation one.**

The engine's computed state is printed as the headline for every company,
above any drafted text, and is written to its own CSV column. Agent prose is
supplementary commentary on a verdict the reader has already seen.

That ordering is the architectural guarantee behind `check_reassurance()` in
agents.py: a drafting layer that writes around the keyword filter can
editorialise, but it cannot overwrite the verdict, because the verdict was
printed first and came from `rules.py`.
"""

import csv
from collections import Counter

from .rules import STATE_ORDER

MARK = {
    "BREACH_LOCKED": "!! BREACH (LOCKED)  ",
    "BREACH_AVOIDABLE": "!! BREACH (AVOIDABLE)",
    "AT_RISK": "?  AT RISK           ",
    "COMPLIANT": "   compliant         ",
    "NOT_APPLICABLE": "   not applicable    ",
    "INSUFFICIENT_DATA": "-- insufficient data ",
}
COLOUR = {
    "BREACH_LOCKED": "\033[31m", "BREACH_AVOIDABLE": "\033[31m",
    "AT_RISK": "\033[33m", "COMPLIANT": "\033[32m",
    "NOT_APPLICABLE": "\033[90m", "INSUFFICIENT_DATA": "\033[90m",
}


def terminal(portfolio, cfg, agentic, tasks=None, use_colour=True):
    L = []
    tint = (lambda s_, t: f"{COLOUR.get(s_, '')}{t}\033[0m") if use_colour \
        else (lambda s_, t: t)
    tasks_by_id = {t["company_id"]: t for t in (tasks or [])}

    L.append("")
    L.append("ufuq -- Emiratisation runway")
    L.append(f"  as of {portfolio.today.isoformat()}   "
             f"{'projected + drafted + gated' if agentic else 'projected only'}")
    L.append("")

    for p in portfolio.projections:
        # The computed verdict, first and unmissable. Anything an agent wrote
        # appears below this line, never in place of it.
        L.append(f"  {tint(p.state, MARK[p.state])}  {p.company_id:<10} "
                 f"{p.company_name}")
        for c in p.checkpoints:
            if c.state == "COMPLIANT" and p.state == "COMPLIANT":
                continue
            runway = (f"{c.runway_days:>5}d runway"
                      if c.runway_days is not None else "    -- runway")
            # Both gaps, labelled. The committed gap decides compliance; the
            # pipeline gap is what remains if every open requisition lands.
            # Printing one unlabelled next to a reason quoting the other is
            # how a reader concludes the tool contradicts itself.
            L.append(f"        {c.year}  target {c.target_pct:>5.1f}%   "
                     f"need {c.required_emirati:>3}  have {c.committed_emirati:>3}"
                     f"   gap {c.committed_gap:>3} committed /"
                     f" {c.pipeline_gap:>3} if all land   {runway}   "
                     f"{c.state}")
            for r in c.reasons:
                L.append(f"              - {r}")

        if p.state in ("INSUFFICIENT_DATA", "NOT_APPLICABLE") and p.reasons:
            for r in p.reasons:
                L.append(f"              - {r}")

        t = tasks_by_id.get(p.company_id)
        if t:
            if t.get("status") == "held":
                L.append(f"        >> HELD: {t.get('status_reason', '')}")
            elif t.get("status") == "released":
                L.append(f"        >> plan: {t.get('plan', '')[:100]}")

        if p.data_gaps:
            for g in p.data_gaps[:4]:
                L.append(f"        DATA GAP: {g}")
        L.append("")

    counts = Counter(p.state for p in portfolio.projections)
    L.append("  " + "   ".join(f"{counts.get(s, 0)} {s.lower()}"
                               for s in STATE_ORDER if counts.get(s)))
    exposure = portfolio.total_exposure()
    if exposure:
        L.append(f"  total exposure if every gap goes unfilled: "
                 f"{exposure:,.2f} AED")
    locked = portfolio.by_state("BREACH_LOCKED")
    if locked:
        L.append(f"  {len(locked)} company(ies) can no longer reach this "
                 f"year's target by hiring -- that is a budgeting "
                 f"conversation, not a recruitment one")
    if tasks:
        st = Counter(t.get("status") for t in tasks)
        L.append(f"  plan review: {st.get('released', 0)} released   "
                 f"{st.get('held', 0)} held")
        for key, label in (("false_reassurance", "reassuring a company in breach"),
                           ("ungrounded_citations", "citing a requisition that does not exist"),
                           ("invented_dates", "stating a date nothing computed"),
                           ("invented_figures", "stating a figure nothing computed")):
            hits = [t for t in tasks if t.get(key)]
            if hits:
                L.append(f"  {len(hits)} held for {label}")
    L.append("")
    L.append(f"  {cfg.verify_note()}")
    L.append("")
    return "\n".join(L)


FIELDNAMES = ["company_id", "company_name", "as_of", "computed_state", "year",
              "target_pct", "projected_skilled", "required_emirati",
              "committed_emirati", "pipeline_emirati", "committed_gap",
              "pipeline_gap", "last_safe_requisition", "runway_days",
              "exposure_aed", "checkpoint_state", "reasons",
              "advice_status", "advice_status_reason", "explanation", "plan"]


def write_csv(path, portfolio, tasks=None):
    tasks_by_id = {t["company_id"]: t for t in (tasks or [])}
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        w.writeheader()
        for p in portfolio.projections:
            t = tasks_by_id.get(p.company_id, {})
            base = {
                "company_id": p.company_id, "company_name": p.company_name,
                "as_of": p.as_of.isoformat() if p.as_of else "",
                # The engine's verdict, in its own column, always.
                "computed_state": p.state,
                "advice_status": t.get("status", ""),
                "advice_status_reason": t.get("status_reason", ""),
                "explanation": t.get("explanation", ""),
                "plan": t.get("plan", ""),
            }
            if not p.checkpoints:
                w.writerow({**base, "reasons": " | ".join(p.reasons)})
                continue
            for c in p.checkpoints:
                w.writerow({
                    **base,
                    "year": c.year, "target_pct": c.target_pct,
                    "projected_skilled": c.projected_skilled,
                    "required_emirati": c.required_emirati,
                    "committed_emirati": c.committed_emirati,
                    "pipeline_emirati": c.pipeline_emirati,
                    "committed_gap": c.committed_gap,
                    "pipeline_gap": c.pipeline_gap,
                    "last_safe_requisition": (
                        c.last_safe_requisition.isoformat()
                        if c.last_safe_requisition else ""),
                    "runway_days": c.runway_days,
                    "exposure_aed": c.exposure_aed,
                    "checkpoint_state": c.state,
                    "reasons": " | ".join(c.reasons),
                })
    return path
