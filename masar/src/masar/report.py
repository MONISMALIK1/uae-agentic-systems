"""Terminal report and the schedule CSV."""

import csv
from collections import Counter

from .rules import VERDICT_ORDER

MARK = {
    "WILL_BOUNCE": "!! WILL BOUNCE",
    "READY": "   READY      ",
    "RISKY": "   RISKY      ",
    "BLOCKED": "   blocked    ",
    "GRANTED": "   granted    ",
    "FILED": "   filed      ",
}
COLOUR = {
    "WILL_BOUNCE": "\033[31m", "READY": "\033[32m", "RISKY": "\033[33m",
    "BLOCKED": "\033[90m", "GRANTED": "\033[90m", "FILED": "\033[36m",
}


def terminal(assessments, cfg, agentic, tasks=None, use_colour=True,
             show_granted=False):
    L = []
    tint = (lambda v, s: f"{COLOUR.get(v, '')}{s}\033[0m") if use_colour \
        else (lambda v, s: s)
    tasks_by_id = {t["project_id"]: t for t in (tasks or [])}

    L.append("")
    L.append("masar -- construction approval sequencing")
    if assessments:
        L.append(f"  as of {assessments[0].today.isoformat()}   "
                 f"{'sequenced + drafted + gated' if agentic else 'sequenced only'}")
    L.append("")

    total_bounce = 0
    for a in assessments:
        L.append(f"  {a.project_id}  {a.project_name}  [{a.jurisdiction}]")
        if a.forecast_completion:
            L.append(f"    forecast completion {a.forecast_completion.isoformat()}"
                     f"   critical path: {' -> '.join(a.critical_path) or '--'}")

        shown = [r for r in a.readiness
                 if show_granted or r.verdict not in ("GRANTED",)]
        for r in shown:
            star = "*" if r.is_critical_path else " "
            when = (r.earliest_file_date.isoformat()
                    if r.earliest_file_date else "--")
            L.append(f"    {tint(r.verdict, MARK[r.verdict])} {star} "
                     f"{r.approval_code:<16} {r.authority[:22]:<24} "
                     f"file from {when}")
            for reason in r.reasons:
                L.append(f"                     - {reason}")
            if r.missing_documents:
                L.append(f"                     - documents missing: "
                         f"{', '.join(r.missing_documents)}")
        total_bounce += len(a.will_bounce())

        t = tasks_by_id.get(a.project_id)
        if t:
            if t.get("status") == "held":
                L.append(f"    >> HELD: {t.get('status_reason', '')}")
            elif t.get("status") == "released":
                L.append(f"    >> advice: {t.get('actions', '')[:110]}")

        if a.data_gaps:
            L.append(f"    DATA GAPS ({len(a.data_gaps)}):")
            for g in a.data_gaps[:5]:
                L.append(f"      {g}")
        L.append("")

    counts = Counter(r.verdict for a in assessments for r in a.readiness)
    L.append("  " + "   ".join(f"{counts.get(v, 0)} {v.lower()}"
                               for v in VERDICT_ORDER))
    if total_bounce:
        L.append(f"  {total_bounce} submission(s) already with an authority "
                 f"will be rejected on sequence -- the cycle spent is lost")
    if tasks:
        st = Counter(t.get("status") for t in tasks)
        L.append(f"  advice review: {st.get('released', 0)} released   "
                 f"{st.get('held', 0)} held")
        for key, label in (("ungrounded_references", "citing a reference the project does not carry"),
                           ("invented_dates", "stating a date no computation produced"),
                           ("overruled_verdicts", "urging a filing the engine marked unfilable")):
            hits = [t for t in tasks if t.get(key)]
            if hits:
                L.append(f"  {len(hits)} project(s) held for {label}")
    L.append("")
    L.append(f"  {cfg.verify_note()}")
    L.append("")
    return "\n".join(L)


FIELDNAMES = ["project_id", "project_name", "jurisdiction", "approval_code",
              "authority", "verdict", "on_critical_path", "reasons",
              "missing_prerequisites", "missing_documents",
              "earliest_file_date", "forecast_grant_date", "reference",
              "status", "status_reason", "recommendation", "explanation",
              "actions", "rationale"]


def write_csv(path, assessments, tasks=None):
    tasks_by_id = {t["project_id"]: t for t in (tasks or [])}
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        w.writeheader()
        for a in assessments:
            t = tasks_by_id.get(a.project_id, {})
            for r in a.readiness:
                w.writerow({
                    "project_id": a.project_id,
                    "project_name": a.project_name,
                    "jurisdiction": a.jurisdiction,
                    "approval_code": r.approval_code,
                    "authority": r.authority,
                    "verdict": r.verdict,
                    "on_critical_path": r.is_critical_path,
                    "reasons": " | ".join(r.reasons),
                    "missing_prerequisites": ";".join(r.missing_prerequisites),
                    "missing_documents": ";".join(r.missing_documents),
                    "earliest_file_date": (r.earliest_file_date.isoformat()
                                           if r.earliest_file_date else ""),
                    "forecast_grant_date": (r.forecast_grant_date.isoformat()
                                            if r.forecast_grant_date else ""),
                    "reference": r.reference,
                    "status": t.get("status", ""),
                    "status_reason": t.get("status_reason", ""),
                    "recommendation": t.get("recommendation", ""),
                    "explanation": t.get("explanation", ""),
                    "actions": t.get("actions", ""),
                    "rationale": t.get("rationale", ""),
                })
    return path
