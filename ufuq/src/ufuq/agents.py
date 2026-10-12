"""Explain the projection, draft the plan -- but never say "you're fine".

Every projection, gap, exposure figure and runway date in this system is
computed in `rules.py`. The agents receive the result and may explain, draft
and recommend against it.

Three checks, because a workforce-planning note fails three ways:

  check_citations()    a requisition reference that does not exist
  check_figures()      a count, date or exposure figure nothing computed
  check_reassurance()  **the one this system is built around.** Language
                       asserting that a company is compliant, on track or
                       safe, for a company the engine computed as in breach

Together those are the Assurance Gate.

`check_reassurance()` exists because of how this system fails. Not with a
wrong number -- with **false comfort**. A company told it is on track does
nothing, and the shortfall accrues quietly until a deadline that was already
unreachable months before anyone looked. An error in the pessimistic
direction costs an unnecessary requisition; an error in the reassuring
direction costs the year.

**An honest limitation, stated here rather than buried.** That check is a
keyword test. It catches the ordinary phrasings of reassurance and it is
straightforwardly evadable by a model writing around them. It is
defence-in-depth, not the guarantee.

The actual guarantee is architectural: `report.py` prints the ENGINE's
computed state as the headline for every company, above any drafted text,
and the CSV carries the computed state in its own column. Agent prose is
supplementary commentary on a verdict the reader has already seen. A drafting
layer that gets creative cannot overwrite the verdict, only editorialise
beneath it.

  projection_explainer  writes the plain-language account of the position
  plan_drafter          drafts the requisition plan that closes the gap
  plan_reviewer         recommends release or hold

The gate can only ever push toward holding.
"""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

MODEL = os.environ.get("UFUQ_MODEL", "claude-opus-5")

# Thinking is on by default on this model, and max_tokens caps thinking and
# response text together. A budget tight enough to truncate the JSON surfaces
# as a parse error, which the gate turns into a hold -- every company would
# hold and it would look like the gate correctly failing safe rather than the
# budget being wrong. See docs/the-assurance-gate.md.
MAX_TOKENS = 16000

_FALLBACK = ({"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
             if MODEL == "claude-opus-5" else {})

# Requisition and company identifiers: REQ-00042, CO-1180.
_ID = re.compile(r"\b([A-Z]{2,6}(?:-[A-Z0-9]+)+)\b")

_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Reassurance phrasings. Deliberately broad, deliberately crude -- see the
# module docstring on why this is defence-in-depth rather than the guarantee.
_REASSURING = re.compile(
    r"\b("
    r"complian(?:t|ce)\b(?!\s+(?:gap|shortfall|risk|breach))"
    r"|on track"
    r"|no (?:action|further action|concern|risk|issue)"
    r"|nothing (?:to do|further)"
    r"|meets? the target"
    r"|within target"
    r"|comfortabl[ey]"
    r"|well[- ]positioned"
    r"|no cause for concern"
    r"|in good standing"
    r"|safe(?:ly)?\b"
    r")", re.IGNORECASE)


def citations_in(text: str) -> set:
    return {m.group(1) for m in _ID.finditer(text or "")
            if any(c.isdigit() for c in m.group(1))}


def dates_in(text: str) -> set:
    return {m.group(1) for m in _DATE.finditer(text or "")}


def _norm_forms(raw):
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return set()
    return {round(val, 2), float(round(val))}


def numbers_in(text: str) -> set:
    """Identifiers and ISO dates are stripped first: REQ-00042 is a
    requisition, not 42, and 2026-12-31 is a date, not three figures."""
    stripped = _DATE.sub(" ", _ID.sub(" ", text or ""))
    out = set()
    for m in _NUMBER.finditer(stripped):
        out |= _norm_forms(m.group(0).replace(",", ""))
    return out


def _collect(value, numbers: set, dates: set, citations: set):
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        numbers |= _norm_forms(value)
    elif isinstance(value, str):
        dates |= dates_in(value)
        citations |= citations_in(value)
        numbers |= numbers_in(value)
    elif isinstance(value, dict):
        for v in value.values():
            _collect(v, numbers, dates, citations)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _collect(v, numbers, dates, citations)


def expand_evidence(facts: dict):
    """Everything an agent may legitimately reference for this company."""
    citations, numbers, dates = set(), set(), set()
    citations |= citations_in(str(facts.get("company_id") or ""))
    citations.update(r for r in (facts.get("requisitions") or []) if r)
    if facts.get("as_of"):
        dates.add(facts["as_of"])
    _collect(facts.get("checkpoints"), numbers, dates, citations)

    return {
        "citations": citations,
        "numbers": numbers,
        "dates": dates,
        # Whether reassuring language is permitted at all for this company.
        "in_breach": facts.get("state") in ("BREACH_LOCKED", "BREACH_AVOIDABLE"),
    }


def check_citations(text: str, allowed: set):
    return sorted(citations_in(text) - allowed)


def check_figures(text: str, allowed_numbers: set, allowed_dates: set):
    bad_dates = sorted(dates_in(text) - allowed_dates)
    bad_numbers = sorted(numbers_in(text) - allowed_numbers)
    return bad_dates, bad_numbers


def check_reassurance(text: str, in_breach: bool):
    """Reassuring language used about a company the engine says is in breach.

    Crude by construction. The architectural guarantee is that the engine's
    verdict is printed above any drafted text; this check is the second line.
    """
    if not in_breach:
        return []
    return sorted({m.group(1).lower() for m in _REASSURING.finditer(text or "")})


EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string",
                        "description": "Plain-language account of where the "
                                       "company stands against each target "
                                       "checkpoint."},
    },
    "required": ["explanation"],
    "additionalProperties": False,
}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "plan": {"type": "string",
                 "description": "The requisition plan: how many roles, opened "
                                "by when, to close the computed gap."},
    },
    "required": ["plan"],
    "additionalProperties": False,
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendation": {"type": "string", "enum": ["release", "hold"]},
        "rationale": {"type": "string",
                      "description": "Reasoning citing the computed figures. "
                                     "A recommendation, not a decision."},
    },
    "required": ["recommendation", "rationale"],
    "additionalProperties": False,
}

EXPLAIN_SYSTEM = """You explain one company's Emiratisation projection to the \
HR director who has to act on it.

Rules:
- State only the computed position you were given. You are not assessing
  compliance -- that has been computed.
- If the computed state is a breach, DO NOT use reassuring language. Do not
  say the company is compliant, on track, safe, comfortable, or that there is
  no action required. Say plainly what the shortfall is.
- Cite requisition references only where you were given them.
- State only figures and dates you were given. Never compute a new total, add
  days to a date, or estimate.
- Three sentences at most."""

PLAN_SYSTEM = """You draft the requisition plan that closes a computed \
Emiratisation gap, for an HR director to review.

Rules:
- The number of roles and the deadline are given to you. Do not recalculate
  them, and do not propose a smaller number than the computed gap.
- If the runway has already closed, say so plainly. The honest plan in that
  case is to budget for the exposure and open requisitions for the following
  year -- not to imply the deadline can still be met.
- Every figure and date must be one you were handed.
- Do not describe the company as compliant or on track when it is not."""

REVIEW_SYSTEM = """You review a drafted Emiratisation plan and recommend \
whether an HR director should act on it.

Rules:
- Cite the computed figures you were given. An uncited claim is unsupported
  and forces a hold.
- You do not decide compliance; it was computed and given to you.
- If the draft reassures a company that is in breach, or proposes fewer hires
  than the computed gap, recommend holding. An unnecessary hold costs a
  meeting; a company that believes it is on track does nothing until the
  deadline has already passed."""


class AgentUnavailable(RuntimeError):
    pass


def _client():
    try:
        import anthropic
    except ImportError as exc:
        raise AgentUnavailable(
            "the `anthropic` package is not installed -- run `pip install "
            "anthropic`, or use --no-agents for the computed projection only"
        ) from exc
    return anthropic.Anthropic()


def _structured(client, system, prompt, schema, effort):
    resp = client.beta.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, system=system,
        output_config={"format": {"type": "json_schema", "schema": schema},
                       "effort": effort},
        messages=[{"role": "user", "content": prompt}],
        **_FALLBACK,
    )
    # Checked before touching resp.content: on a refusal the content list is
    # empty or partial, so reading it first would raise the wrong error.
    if resp.stop_reason == "refusal":
        raise AgentUnavailable("model declined this item")
    if resp.stop_reason == "max_tokens":
        raise AgentUnavailable(
            f"model hit the {MAX_TOKENS}-token cap before finishing its "
            f"reply; raise MAX_TOKENS in agents.py")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))


def _handle(client, task):
    facts_json = json.dumps(task["facts"])

    try:
        explained = _structured(client, EXPLAIN_SYSTEM,
                                f"Company: {task['label']}\n"
                                f"Projection: {facts_json}",
                                EXPLAIN_SCHEMA, "low")
    except AgentUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        task["error"] = f"projection explanation failed: {exc}"
        return task
    task["explanation"] = explained["explanation"]

    try:
        drafted = _structured(client, PLAN_SYSTEM,
                              f"Company: {task['label']}\n"
                              f"Projection: {facts_json}\n"
                              f"Position: {task['explanation']}",
                              PLAN_SCHEMA, "medium")
    except Exception as exc:  # noqa: BLE001
        task["error"] = f"plan drafting failed: {exc}"
        return task
    task["plan"] = drafted["plan"]

    try:
        review = _structured(client, REVIEW_SYSTEM,
                             f"Company: {task['label']}\n"
                             f"Projection: {facts_json}\n"
                             f"Position: {task['explanation']}\n"
                             f"Drafted plan: {task['plan']}\n\n"
                             f"Should an HR director act on this?",
                             REVIEW_SCHEMA, "high")
    except Exception as exc:  # noqa: BLE001
        task["error"] = f"review failed: {exc}"
        return task
    task["recommendation"] = review["recommendation"]
    task["rationale"] = review["rationale"]
    return task


def gate(task, allowed: dict):
    """The Assurance Gate. Runs after the agents, always. Holds only."""
    if task.get("error"):
        task["status"] = "held"
        task["status_reason"] = task["error"]
        return task

    blob = " ".join(str(task.get(k, "")) for k in
                    ("explanation", "plan", "rationale"))

    ungrounded = check_citations(blob, allowed["citations"])
    if ungrounded:
        task["status"] = "held"
        task["status_reason"] = ("model cited a requisition that does not "
                                 "exist: " + ", ".join(ungrounded[:6]))
        task["ungrounded_citations"] = ungrounded
        return task

    reassuring = check_reassurance(blob, allowed["in_breach"])
    if reassuring:
        task["status"] = "held"
        task["status_reason"] = ("model reassured a company the engine "
                                 "computed as in breach: "
                                 + ", ".join(f"'{r}'" for r in reassuring[:6]))
        task["false_reassurance"] = reassuring
        return task

    bad_dates, bad_numbers = check_figures(blob, allowed["numbers"],
                                           allowed["dates"])
    if bad_dates:
        task["status"] = "held"
        task["status_reason"] = ("model stated a date no computation "
                                 "produced: " + ", ".join(bad_dates[:6]))
        task["invented_dates"] = bad_dates
        return task
    if bad_numbers:
        task["status"] = "held"
        shown = ", ".join(f"{n:,.2f}".rstrip("0").rstrip(".")
                          for n in bad_numbers[:6])
        task["status_reason"] = ("model stated a figure no computation "
                                 "produced: " + shown)
        task["invented_figures"] = bad_numbers
        return task

    if task.get("recommendation") == "hold":
        task["status"] = "held"
        task["status_reason"] = ("reviewer recommended holding: "
                                 + task.get("rationale", ""))
        return task

    task["status"] = "released"
    task["status_reason"] = ""
    return task


def run(tasks, workers=6):
    client = _client()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda t: _handle(client, t), tasks))
