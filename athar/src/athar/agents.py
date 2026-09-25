"""Explain the attribution, draft the recovery note -- but never name a name.

Every attribution state, dispute clock and recoverability verdict in this
system is computed in `rules.py`. The agents receive the result as citable
identifiers and computed figures, and may explain, draft and recommend
against them.

Three checks, because a recovery notice fails three ways:

  check_citations()   a fine, assignment or contract reference that does not
                      exist in this run
  check_figures()     an amount or a day count nothing computed
  check_naming()      **the one that matters here.** A driver identifier
                      named in connection with a fine whose computed state is
                      CONTESTED, COMPANY or UNATTRIBUTABLE

Together those are the Attribution Gate.

`check_naming()` exists because of what this system's output actually is. It
is not a report. It is a document that says a named person incurred a
penalty, and it leads to a card being charged or a conversation about someone's
wages. **A false attribution is an accusation.** The deterministic core
refuses to name anyone it cannot establish; the gate makes sure the drafting
layer cannot undo that refusal by inferring a name from context the engine
deliberately left ambiguous.

The check is scoped to identifiers rather than prose. A draft may say "the
renter" or "whoever held the vehicle" about a contested fine -- that is
honest. What it may not do is attach a driver ID to it.

  attribution_explainer  writes the plain-language account of the join
  notice_drafter         drafts the recovery or write-off note
  recovery_reviewer      recommends release or hold, and is graded on its own
                         citations, figures and naming discipline

The gate can only ever push toward holding. Nothing here charges a card,
deducts from wages, or contacts anybody.
"""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

MODEL = os.environ.get("ATHAR_MODEL", "claude-opus-5")

# Thinking is on by default on this model, and max_tokens caps thinking and
# response text together. A budget tight enough to truncate the JSON surfaces
# as a parse error, which the gate turns into a hold -- every fine would hold
# and it would look like the gate correctly failing safe rather than the
# budget being wrong. See docs/the-attribution-gate.md.
MAX_TOKENS = 16000

_FALLBACK = ({"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
             if MODEL == "claude-opus-5" else {})

# Identifiers: FN-00042, ASG-00117, DRV-9931, RC-2026-8842. Matches the whole
# hyphenated run and filters for a digit afterwards, so that an ordinary
# hyphenated capitalised phrase ("OFF-HIRE", "NON-RECOVERABLE") is not read as
# a reference.
_ID = re.compile(r"\b([A-Z]{2,6}(?:-[A-Z0-9]+)+)\b")

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


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
    """Identifiers are stripped first: ASG-00117 is a custody record, not
    117 dirhams."""
    stripped = _ID.sub(" ", text or "")
    out = set()
    for m in _NUMBER.finditer(stripped):
        out |= _norm_forms(m.group(0).replace(",", ""))
    return out


def _collect_numbers(value, into: set):
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        into |= _norm_forms(value)
    elif isinstance(value, str):
        for m in _NUMBER.finditer(_ID.sub(" ", value)):
            into |= _norm_forms(m.group(0).replace(",", ""))
    elif isinstance(value, dict):
        for v in value.values():
            _collect_numbers(v, into)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _collect_numbers(v, into)


def expand_evidence(facts: dict):
    """Everything an agent may legitimately reference for this run.

    `unnameable` carries the driver identifiers that must NOT appear: every
    driver id that exists anywhere in the fleet, minus the ones the engine
    actually attributed. A name the engine refused to assert is a name the
    drafting layer may not assert either.
    """
    citations = set()
    numbers = set()
    attributed_drivers = set()
    all_drivers = set(facts.get("fleet_driver_ids") or [])

    for f in facts.get("fines") or []:
        for key in ("fine_id", "plate", "assignment_id", "driver_id"):
            v = f.get(key)
            if v:
                citations |= citations_in(str(v))
        _collect_numbers(f.get("amount_aed"), numbers)
        _collect_numbers(f.get("days_to_dispute"), numbers)
        for r in f.get("reasons") or []:
            citations |= citations_in(r)
            _collect_numbers(r, numbers)
        if f.get("state") == "ATTRIBUTED" and f.get("driver_id"):
            attributed_drivers.add(f["driver_id"])

    return {
        "citations": citations,
        "numbers": numbers,
        "unnameable": all_drivers - attributed_drivers,
    }


def check_citations(text: str, allowed: set):
    return sorted(citations_in(text) - allowed)


def check_figures(text: str, allowed: set):
    return sorted(numbers_in(text) - allowed)


def check_naming(text: str, unnameable: set):
    """Driver identifiers the engine declined to attribute.

    The engine's refusal to name someone is the safety property of this whole
    system. This check makes it unforgeable downstream.
    """
    found = citations_in(text)
    return sorted(found & set(unnameable))


EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string",
                        "description": "Plain-language account of how each "
                                       "fine was or was not attributed."},
    },
    "required": ["explanation"],
    "additionalProperties": False,
}

NOTICE_SCHEMA = {
    "type": "object",
    "properties": {
        "notice": {"type": "string",
                   "description": "What to do with each fine: recover, "
                                  "gather evidence, contest, or absorb."},
    },
    "required": ["notice"],
    "additionalProperties": False,
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendation": {"type": "string", "enum": ["release", "hold"]},
        "rationale": {"type": "string",
                      "description": "Reasoning citing fine and assignment "
                                     "identifiers. A recommendation, not a "
                                     "decision."},
    },
    "required": ["recommendation", "rationale"],
    "additionalProperties": False,
}

EXPLAIN_SYSTEM = """You explain a batch of traffic fines and how each was \
matched to a custody record, for the fleet administrator who has to work them.

Rules:
- State only the attribution states you were given. You are not deciding who
  was driving -- that has been computed for you, and where it could not be
  computed the answer is that nobody knows.
- NEVER name or identify a driver for a fine whose state is CONTESTED,
  COMPANY or UNATTRIBUTABLE. You may say "the renter" or "whoever held the
  vehicle"; you may not attach a driver identifier.
- Cite fine and assignment identifiers only where you were given them.
- State only figures you were given. Do not total, net or estimate.
- Four sentences at most."""

NOTICE_SYSTEM = """You draft this batch's recovery actions for a fleet \
administrator to review and execute.

Rules:
- Only recommend recovering from a person for a fine whose state is
  ATTRIBUTED and whose evidence is complete. For a contested fine, the action
  is to find evidence or absorb it -- never to charge someone.
- NEVER attach a driver identifier to a fine the engine did not attribute.
- For an employee assignment, recovery from wages is constrained by UAE
  labour law and the employment contract. Recommend a conversation, never a
  deduction.
- Every amount and day count must be one you were handed.
- Do not state that anything has been charged or recovered; it has not."""

REVIEW_SYSTEM = """You review drafted recovery actions and recommend whether \
a fleet administrator should act on them.

Rules:
- Cite identifiers you were given. An uncited claim is unsupported and forces
  a hold.
- Use only the figures you were given.
- You do not decide attribution; that was computed and given to you.
- If the draft names anyone for a fine the engine did not attribute, or
  recommends charging a card on incomplete evidence, recommend holding. An
  unnecessary hold costs minutes; a wrongly charged renter costs a lost
  chargeback and a complaint, and a wrongly accused employee costs far more
  than that."""


class AgentUnavailable(RuntimeError):
    pass


def _client():
    try:
        import anthropic
    except ImportError as exc:
        raise AgentUnavailable(
            "the `anthropic` package is not installed -- run `pip install "
            "anthropic`, or use --no-agents for the computed ledger only"
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
                                f"Batch: {task['label']}\nLedger: {facts_json}",
                                EXPLAIN_SCHEMA, "low")
    except AgentUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        task["error"] = f"attribution explanation failed: {exc}"
        return task
    task["explanation"] = explained["explanation"]

    try:
        drafted = _structured(client, NOTICE_SYSTEM,
                              f"Batch: {task['label']}\nLedger: {facts_json}\n"
                              f"Account: {task['explanation']}",
                              NOTICE_SCHEMA, "medium")
    except Exception as exc:  # noqa: BLE001
        task["error"] = f"notice drafting failed: {exc}"
        return task
    task["notice"] = drafted["notice"]

    try:
        review = _structured(client, REVIEW_SYSTEM,
                             f"Batch: {task['label']}\nLedger: {facts_json}\n"
                             f"Account: {task['explanation']}\n"
                             f"Drafted actions: {task['notice']}\n\n"
                             f"Should an administrator act on this?",
                             REVIEW_SCHEMA, "high")
    except Exception as exc:  # noqa: BLE001
        task["error"] = f"review failed: {exc}"
        return task
    task["recommendation"] = review["recommendation"]
    task["rationale"] = review["rationale"]
    return task


def gate(task, allowed: dict):
    """The Attribution Gate. Runs after the agents, always.

    Checks the drafted text against the computed ledger directly. Can only
    ever push toward a hold.
    """
    if task.get("error"):
        task["status"] = "held"
        task["status_reason"] = task["error"]
        return task

    blob = " ".join(str(task.get(k, "")) for k in
                    ("explanation", "notice", "rationale"))

    ungrounded = check_citations(blob, allowed["citations"])
    if ungrounded:
        task["status"] = "held"
        task["status_reason"] = ("model cited an identifier that does not "
                                 "exist in this run: " + ", ".join(ungrounded[:6]))
        task["ungrounded_citations"] = ungrounded
        return task

    named = check_naming(blob, allowed["unnameable"])
    if named:
        task["status"] = "held"
        task["status_reason"] = ("model named a driver the engine declined to "
                                 "attribute: " + ", ".join(named[:6]))
        task["improper_naming"] = named
        return task

    invented = check_figures(blob, allowed["numbers"])
    if invented:
        task["status"] = "held"
        shown = ", ".join(f"{n:,.2f}".rstrip("0").rstrip(".") for n in invented[:6])
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
