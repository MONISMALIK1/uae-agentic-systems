"""Explain the sequence, draft the advice -- but never produce a date.

Every readiness verdict, prerequisite check, forecast date and critical path
in this system is computed in `rules.py`. The agents receive the result as
citable authority references and computed dates, and may explain, draft and
recommend against them. They may not introduce a reference they were not
handed, and they may not state a date this system did not compute.

That restriction is enforced, not requested, and it is enforced in three
directions, because sequencing advice fails in three ways:

  check_references()  an authority file or permit number that does not exist
                      on this project -- advice citing a permit nobody can
                      produce is worse than no advice
  check_dates()       a date `rules.py` did not compute. This is the one that
                      actually gets acted on: a wrong date does not look
                      wrong, it looks like a date, and it is discovered a
                      month later when the submission bounces
  check_verdict()     advice to FILE an approval the engine says WILL_BOUNCE
                      or is BLOCKED. The engine owns readiness; the model
                      does not get a vote on it

Together those are the Sequencing Gate.

  sequence_explainer  writes the plain-language account of what is blocking
  action_drafter      drafts the file-now / defer / chase advice
  schedule_reviewer   recommends proceed or hold, and is graded on its own
                      references, dates and consistency with the engine

The gate can only ever push toward holding. It has no path to release advice
the reviewer did not already recommend releasing, and no path from held back
to released. A planning engineer files every submission; nothing here
transmits anything to an authority.
"""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

MODEL = os.environ.get("MASAR_MODEL", "claude-opus-5")

# Thinking is on by default on this model, and max_tokens caps thinking and
# response text together. These replies are short, but a tight budget
# truncates the JSON mid-object -- which surfaces as a parse error, which the
# gate turns into a hold. Every project would hold and it would look like the
# gate correctly failing safe rather than the budget being wrong.
MAX_TOKENS = 16000

# If a safety classifier declines an item, retry on the recommended model
# inside the same call rather than failing the project. Sent only for the
# default model: an overridden one may not accept the parameter.
_FALLBACK = ({"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
             if MODEL == "claude-opus-5" else {})

# An authority reference, bracketed or bare: BP-2026-9902, DCD-2026-8812,
# DEWA-NOC-9931. Matches the whole hyphenated run -- an earlier version
# stopped at the first segment (BP-2026) because a hyphen satisfies \b, which
# then reported every real reference as ungrounded.
#
# A digit is required somewhere in the run, so that an ordinary hyphenated
# capitalised phrase ("FIRE-SAFETY", "AS-BUILT") is not read as a reference
# and held against an otherwise good draft. That filter is applied in
# references_in() rather than in the pattern, because expressing "at least
# one digit anywhere across the whole run" in the regex itself is far less
# readable than checking it afterwards.
_REF = re.compile(r"\b([A-Z]{2,6}(?:-[A-Z0-9]+)+)\b")

# ISO dates are the only date form this system emits, and the only form the
# agents are permitted to state. A prose date ("mid-March") states nothing
# checkable and is not a violation -- it is also not actionable, which the
# prompts discourage.
_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

# Approval codes, used for the verdict-consistency check.
_CODE = re.compile(r"\b([A-Z][A-Z_]{2,24})\b")

_FILE_VERB = re.compile(
    r"\b(file|submit|lodge|send)\b[^.]{0,80}?\b(now|immediately|today|this week)\b",
    re.IGNORECASE)


def references_in(text: str) -> set:
    return {m.group(1) for m in _REF.finditer(text or "")
            if any(c.isdigit() for c in m.group(1))}


def dates_in(text: str) -> set:
    return {m.group(1) for m in _DATE.finditer(text or "")}


def codes_in(text: str) -> set:
    return {m.group(1) for m in _CODE.finditer(text or "")}


def expand_evidence(facts: dict):
    """Everything an agent may legitimately reference for this project.

    References come from the project's own authority file numbers. Dates come
    from the computed date set *and* from any date appearing in a finding --
    findings are written by `rules.py`, so a date inside one is a computed
    date by construction.
    """
    references = set(v for v in (facts.get("references") or {}).values() if v)
    dates = set((facts.get("dates") or {}).values())
    dates.add(facts.get("today", ""))
    dates.discard("")

    blocked = set()
    for f in facts.get("findings") or []:
        references |= references_in(" ".join(f.get("reasons") or []))
        dates |= dates_in(" ".join(f.get("reasons") or []))
        if f.get("verdict") in ("WILL_BOUNCE", "BLOCKED"):
            blocked.add(f.get("approval"))

    return {"references": references, "dates": dates, "unfilable": blocked}


def check_references(text: str, allowed: set):
    """References in `text` that this project does not carry."""
    return sorted(references_in(text) - allowed)


def check_dates(text: str, allowed: set):
    """Dates in `text` that no computation in rules.py produced."""
    return sorted(dates_in(text) - allowed)


def check_verdict(text: str, unfilable: set):
    """Approvals the draft urges filing that the engine says cannot be filed.

    The engine owns readiness. A model that reads a blocked approval's
    reasons and concludes "file it anyway" is overruling a computation, and
    the whole system exists to stop exactly that error being made by a human
    under deadline pressure -- so it certainly must not be made here.
    """
    if not _FILE_VERB.search(text or ""):
        return []
    return sorted(codes_in(text) & set(unfilable))


EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string",
                        "description": "Plain-language account of what is "
                                       "blocking this project's next "
                                       "submissions, for the planning "
                                       "engineer."},
    },
    "required": ["explanation"],
    "additionalProperties": False,
}

ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "actions": {"type": "string",
                    "description": "What to file now, what to defer, and what "
                                   "to chase -- each naming the approval and "
                                   "the reason."},
    },
    "required": ["actions"],
    "additionalProperties": False,
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendation": {"type": "string", "enum": ["release", "hold"]},
        "rationale": {"type": "string",
                      "description": "Reasoning citing approval codes and "
                                     "references. A recommendation, not a "
                                     "decision."},
    },
    "required": ["recommendation", "rationale"],
    "additionalProperties": False,
}

EXPLAIN_SYSTEM = """You explain one construction project's approval position \
to the planning engineer who has to act on it this week.

Rules:
- State only the readiness verdicts you were given. You are not assessing
  whether an approval is ready -- that has been computed for you.
- Cite authority references only if you were given them. Never invent one.
- State only dates you were given, in YYYY-MM-DD form. Never compute a new
  date, add days to one, or estimate. If you need to describe timing you were
  not given, describe it in words rather than inventing a date.
- Three sentences at most, plain and specific."""

ACTION_SYSTEM = """You draft this week's approval actions for a planning \
engineer to review and execute.

Rules:
- Only recommend filing an approval whose computed verdict is READY. An
  approval marked BLOCKED or WILL_BOUNCE must never be described as something
  to file now -- say what it is waiting on instead.
- Every date must be one you were handed, in YYYY-MM-DD form. Do not add,
  subtract or estimate dates.
- Cite authority references only where you were given them.
- Say what to file, what to defer and what to chase. Do not state that
  anything has been filed; it has not."""

REVIEW_SYSTEM = """You review drafted approval advice and recommend whether a \
planning engineer should act on it, for a person who makes the final call.

Rules:
- Cite approval codes and references you were given. An uncited claim is
  treated as unsupported and forces a hold recommendation.
- Use only the dates you were given.
- You are recommending, not deciding, and you do not decide whether an
  approval is ready -- that classification was given to you.
- If the advice urges filing anything the engine marked BLOCKED or
  WILL_BOUNCE, recommend holding. A planning engineer can release an
  unnecessary hold in minutes; a submission filed out of sequence costs a
  full authority cycle that cannot be recovered."""


class AgentUnavailable(RuntimeError):
    pass


def _client():
    try:
        import anthropic
    except ImportError as exc:
        raise AgentUnavailable(
            "the `anthropic` package is not installed -- run `pip install "
            "anthropic`, or use --no-agents for the computed schedule only"
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
    """`task` is a dict: {project_id, label, facts, allowed}."""
    facts_json = json.dumps(task["facts"])

    try:
        explained = _structured(client, EXPLAIN_SYSTEM,
                                f"Project: {task['label']}\nState: {facts_json}",
                                EXPLAIN_SCHEMA, "low")
    except AgentUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        task["error"] = f"sequence explanation failed: {exc}"
        return task
    task["explanation"] = explained["explanation"]

    try:
        drafted = _structured(client, ACTION_SYSTEM,
                              f"Project: {task['label']}\nState: {facts_json}\n"
                              f"Position: {task['explanation']}",
                              ACTION_SCHEMA, "medium")
    except Exception as exc:  # noqa: BLE001
        task["error"] = f"action drafting failed: {exc}"
        return task
    task["actions"] = drafted["actions"]

    try:
        review = _structured(client, REVIEW_SYSTEM,
                             f"Project: {task['label']}\nState: {facts_json}\n"
                             f"Position: {task['explanation']}\n"
                             f"Drafted actions: {task['actions']}\n\n"
                             f"Should a planning engineer act on this?",
                             REVIEW_SCHEMA, "high")
    except Exception as exc:  # noqa: BLE001
        task["error"] = f"review failed: {exc}"
        return task
    task["recommendation"] = review["recommendation"]
    task["rationale"] = review["rationale"]
    return task


def gate(task, allowed: dict):
    """The Sequencing Gate. Runs after the agents, always.

    Checks the drafted text against the computed evidence directly -- not
    against the model's account of whether it stayed inside the evidence.
    Can only ever push toward a hold.
    """
    if task.get("error"):
        task["status"] = "held"
        task["status_reason"] = task["error"]
        return task

    blob = " ".join(str(task.get(k, "")) for k in
                    ("explanation", "actions", "rationale"))

    ungrounded = check_references(blob, allowed["references"])
    if ungrounded:
        task["status"] = "held"
        task["status_reason"] = ("model cited an authority reference this "
                                 "project does not carry: "
                                 + ", ".join(ungrounded[:6]))
        task["ungrounded_references"] = ungrounded
        return task

    invented = check_dates(blob, allowed["dates"])
    if invented:
        task["status"] = "held"
        task["status_reason"] = ("model stated a date no computation "
                                 "produced: " + ", ".join(invented[:6]))
        task["invented_dates"] = invented
        return task

    overruled = check_verdict(task.get("actions", ""), allowed["unfilable"])
    if overruled:
        task["status"] = "held"
        task["status_reason"] = ("model urged filing an approval the engine "
                                 "marked unfilable: " + ", ".join(overruled[:6]))
        task["overruled_verdicts"] = overruled
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
