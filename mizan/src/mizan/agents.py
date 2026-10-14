"""Draft the claim -- but never claim more than the evidence supports.

Every evidence test, justified-demand figure and recoverable amount is
computed in `rules.py`. The agents receive the result and may explain, draft
and recommend against it.

Three checks, because a claim against a regulated utility fails three ways:

  check_citations()  a unit or building reference that is not in this run
  check_overclaim()  **the one this system is built around.** A dirham figure
                     presented as a recovery that EXCEEDS the computed
                     ceiling, or any claim language about a unit whose
                     evidence the engine ruled insufficient
  check_figures()    a figure nothing computed at all

Together those are the Claim Gate.

`check_overclaim()` is a different shape from the membership checks in the
other systems here. Those ask *is this figure in the evidence set?*. This one
asks *is this figure larger than the evidence permits?* -- a bound, not a
lookup. That matters because the characteristic failure of a billing claim is
not inventing a number from nothing. It is rounding a defensible number
upward until the whole claim becomes contestable, and a provider's engineer
only has to discredit the overreach to have the legitimate part dismissed
with it.

The second half of the check is the harder one: a unit the engine marked
INSUFFICIENT_EVIDENCE must not have claim language attached to it at all. The
engine refused to make a finding; the drafting layer may not manufacture one.

  position_explainer  writes the plain-language account of the allocation
  claim_drafter       drafts the claim narrative for the provider
  claim_reviewer      recommends release or hold

The gate can only ever push toward holding.
"""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

MODEL = os.environ.get("MIZAN_MODEL", "claude-opus-5")

# Thinking is on by default on this model, and max_tokens caps thinking and
# response text together. A budget tight enough to truncate the JSON surfaces
# as a parse error, which the gate turns into a hold -- every claim would hold
# and it would look like the gate correctly failing safe rather than the
# budget being wrong. See docs/the-claim-gate.md.
MAX_TOKENS = 16000

_FALLBACK = ({"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
             if MODEL == "claude-opus-5" else {})

_ID = re.compile(r"\b([A-Z]{2,6}(?:-[A-Z0-9]+)+)\b")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

# A figure presented as money being sought back. The window is bounded so a
# sentence mentioning a refund and, separately, an unrelated figure does not
# read as a claim of that figure.
_CLAIM_AMOUNT = re.compile(
    r"(?:recover|refund|reclaim|credit|rebate|claim|owed|due back|"
    r"overcharged?|repay)\w*\b[^.]{0,60}?"
    r"(\d[\d,]*(?:\.\d+)?)\s*(?:AED|dirham)?"
    r"|(\d[\d,]*(?:\.\d+)?)\s*(?:AED|dirhams?)\b[^.]{0,40}?\b"
    r"(?:recover|refund|reclaim|credit|rebate|claim|owed|repay)",
    re.IGNORECASE)

# Language asserting a unit is over-allocated or that money is owed.
_CLAIM_LANGUAGE = re.compile(
    r"\b(over[- ]?allocat\w*|over[- ]?charg\w*|excess (?:capacity|RT|tons?)"
    r"|refund|reclaim|recover\w*|rebate|credit note|owed)\b", re.IGNORECASE)


def citations_in(text: str) -> set:
    return {m.group(1) for m in _ID.finditer(text or "")
            if any(c.isdigit() for c in m.group(1))}


def _norm_forms(raw):
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return set()
    return {round(val, 2), float(round(val))}


def numbers_in(text: str) -> set:
    stripped = _ID.sub(" ", text or "")
    out = set()
    for m in _NUMBER.finditer(stripped):
        out |= _norm_forms(m.group(0).replace(",", ""))
    return out


def claim_amounts_in(text: str):
    """Figures the text presents as money being sought back."""
    stripped = _ID.sub(" ", text or "")
    out = set()
    for m in _CLAIM_AMOUNT.finditer(stripped):
        raw = m.group(1) or m.group(2)
        if raw:
            try:
                out.add(float(raw.replace(",", "")))
            except ValueError:
                continue
    return out


def _collect(value, numbers: set, citations: set):
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        numbers |= _norm_forms(value)
    elif isinstance(value, str):
        citations |= citations_in(value)
        numbers |= numbers_in(value)
    elif isinstance(value, dict):
        for v in value.values():
            _collect(v, numbers, citations)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _collect(v, numbers, citations)


def expand_evidence(facts: dict, blocked_units=()):
    """Everything an agent may legitimately reference.

    `ceiling` bounds what may be claimed. `blocked_units` are the units whose
    evidence the engine ruled insufficient -- they may be described, but no
    claim language may attach to them.
    """
    citations, numbers = set(), set()
    _collect(facts.get("units"), numbers, citations)
    _collect(facts.get("portfolio_ceiling_aed"), numbers, citations)

    return {
        "citations": citations,
        "numbers": numbers,
        "ceiling": float(facts.get("portfolio_ceiling_aed") or 0.0),
        "blocked_units": set(blocked_units),
    }


def check_citations(text: str, allowed: set):
    return sorted(citations_in(text) - allowed)


def check_overclaim(text: str, ceiling: float, blocked_units: set):
    """Claims larger than the evidence permits, or attached to units that
    have no finding at all.

    Returns a list of human-readable violations.
    """
    violations = []

    for amount in sorted(claim_amounts_in(text)):
        if amount > round(ceiling, 2) + 0.01:
            violations.append(
                f"claims {amount:,.2f} AED against a computed ceiling of "
                f"{ceiling:,.2f} AED")

    if blocked_units and _CLAIM_LANGUAGE.search(text or ""):
        named = sorted(citations_in(text) & set(blocked_units))
        for unit_id in named:
            violations.append(
                f"attaches claim language to {unit_id}, whose evidence the "
                f"engine ruled insufficient to support any finding")

    return violations


def check_figures(text: str, allowed: set):
    return sorted(numbers_in(text) - allowed)


EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string",
                        "description": "Plain-language account of which units "
                                       "are over-allocated and on what "
                                       "evidence."},
    },
    "required": ["explanation"],
    "additionalProperties": False,
}

CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "claim": {"type": "string",
                  "description": "The claim narrative for the provider: which "
                                 "units, what evidence, what is sought."},
    },
    "required": ["claim"],
    "additionalProperties": False,
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendation": {"type": "string", "enum": ["release", "hold"]},
        "rationale": {"type": "string",
                      "description": "Reasoning citing unit references and "
                                     "computed figures."},
    },
    "required": ["recommendation", "rationale"],
    "additionalProperties": False,
}

EXPLAIN_SYSTEM = """You explain a district-cooling capacity-charge review to \
the property manager who has to decide whether to dispute it.

Rules:
- State only the computed positions you were given. You are not deciding
  whether a unit is over-allocated -- that has been computed.
- Never describe a unit as over-allocated, overcharged, or owed money if its
  evidence was ruled insufficient. For those units, say only that the
  evidence window cannot support a finding yet.
- Cite unit references only where you were given them.
- State only figures you were given. Never total, scale or estimate.
- Three sentences at most."""

CLAIM_SYSTEM = """You draft a capacity-allocation claim for a property \
manager to review before it goes to the cooling provider.

Rules:
- The recoverable amount is a CEILING computed from the evidence. Never claim
  more than it. Claiming above it invites the provider's engineer to
  discredit the overreach and have the whole case dismissed with it.
- Only units with a computed over-allocation finding may appear as claims. A
  unit whose evidence was ruled insufficient must not be claimed for at all.
- Rest the claim on the observed peak and the headroom allowance you were
  given. Do not argue that a system should be sized with no margin.
- Every figure must be one you were handed.
- Do not state that anything has been submitted or agreed; it has not."""

REVIEW_SYSTEM = """You review a drafted capacity-allocation claim and \
recommend whether a property manager should submit it.

Rules:
- Cite the unit references and computed figures you were given.
- You do not decide whether a unit is over-allocated; that was computed.
- If the draft claims more than the computed ceiling, or claims for a unit
  with insufficient evidence, recommend holding. An unnecessary hold costs a
  week; an overreaching claim gets the legitimate part dismissed too, and it
  does not get re-heard."""


class AgentUnavailable(RuntimeError):
    pass


def _client():
    try:
        import anthropic
    except ImportError as exc:
        raise AgentUnavailable(
            "the `anthropic` package is not installed -- run `pip install "
            "anthropic`, or use --no-agents for the computed review only"
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
                                f"Review: {task['label']}\n"
                                f"Findings: {facts_json}",
                                EXPLAIN_SCHEMA, "low")
    except AgentUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        task["error"] = f"position explanation failed: {exc}"
        return task
    task["explanation"] = explained["explanation"]

    try:
        drafted = _structured(client, CLAIM_SYSTEM,
                              f"Review: {task['label']}\n"
                              f"Findings: {facts_json}\n"
                              f"Position: {task['explanation']}",
                              CLAIM_SCHEMA, "medium")
    except Exception as exc:  # noqa: BLE001
        task["error"] = f"claim drafting failed: {exc}"
        return task
    task["claim"] = drafted["claim"]

    try:
        review = _structured(client, REVIEW_SYSTEM,
                             f"Review: {task['label']}\n"
                             f"Findings: {facts_json}\n"
                             f"Position: {task['explanation']}\n"
                             f"Drafted claim: {task['claim']}\n\n"
                             f"Should a property manager submit this?",
                             REVIEW_SCHEMA, "high")
    except Exception as exc:  # noqa: BLE001
        task["error"] = f"review failed: {exc}"
        return task
    task["recommendation"] = review["recommendation"]
    task["rationale"] = review["rationale"]
    return task


def gate(task, allowed: dict):
    """The Claim Gate. Runs after the agents, always. Holds only."""
    if task.get("error"):
        task["status"] = "held"
        task["status_reason"] = task["error"]
        return task

    blob = " ".join(str(task.get(k, "")) for k in
                    ("explanation", "claim", "rationale"))

    ungrounded = check_citations(blob, allowed["citations"])
    if ungrounded:
        task["status"] = "held"
        task["status_reason"] = ("model cited a unit that is not in this "
                                 "review: " + ", ".join(ungrounded[:6]))
        task["ungrounded_citations"] = ungrounded
        return task

    overclaims = check_overclaim(blob, allowed["ceiling"],
                                 allowed["blocked_units"])
    if overclaims:
        task["status"] = "held"
        task["status_reason"] = "overclaim -- " + "; ".join(overclaims[:3])
        task["overclaims"] = overclaims
        return task

    invented = check_figures(blob, allowed["numbers"])
    if invented:
        task["status"] = "held"
        shown = ", ".join(f"{n:,.2f}".rstrip("0").rstrip(".")
                          for n in invented[:6])
        task["status_reason"] = ("model stated a figure no computation "
                                 "produced: " + shown)
        task["invented_figures"] = invented
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
