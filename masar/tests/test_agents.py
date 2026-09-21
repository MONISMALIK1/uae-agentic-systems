"""The Sequencing Gate, against a stubbed client.

The gate checks three things the model cannot be trusted to self-report:
that every authority reference it cited exists on this project, that every
date it stated was computed by `rules.py`, and that it did not urge filing
something the engine marked unfilable. All three are asserted against clean,
fluent, confident drafts -- because fluency is the failure mode, and a wrong
date does not look wrong. It looks like a date.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date  # noqa: E402

from masar import agents, projects, rules  # noqa: E402
from masar.config import Config  # noqa: E402

TODAY = date(2026, 9, 21)


def _facts():
    """Real evidence from a real assessment, not a hand-built dict.

    Marina Tower C: the building permit was filed 2026-07-02 while DEWA_NOC
    is still with the authority -- so BUILDING_PERMIT is WILL_BOUNCE and is
    in the unfilable set.
    """
    p = projects.Project(project_id="PRJ-001", project_name="Marina Tower C",
                         jurisdiction="dubai_municipality")
    granted = {
        "AFF": ("AFF-2026-1144", date(2026, 5, 8)),
        "CONCEPT": ("CON-2026-3301", date(2026, 6, 1)),
        "DCD_DESIGN": ("DCD-2026-8812", date(2026, 6, 23)),
        "SEWER_NOC": ("SEW-2026-2204", date(2026, 6, 28)),
        "RTA_NOC": ("RTA-2026-7719", date(2026, 7, 1)),
        "TELECOM_NOC": ("TEL-2026-4408", date(2026, 6, 26)),
    }
    for code, (ref, on) in granted.items():
        p.states[code] = projects.ApprovalState(
            "PRJ-001", code, status="granted", granted_on=on, reference=ref)
    p.states["DEWA_NOC"] = projects.ApprovalState(
        "PRJ-001", "DEWA_NOC", status="filed", filed_on=date(2026, 6, 10),
        reference="DEWA-2026-5510")
    p.states["BUILDING_PERMIT"] = projects.ApprovalState(
        "PRJ-001", "BUILDING_PERMIT", status="filed", filed_on=date(2026, 7, 2),
        reference="BP-2026-9902")
    return rules.assess(p, Config(), TODAY).facts()


def _task():
    facts = _facts()
    return {"project_id": "PRJ-001",
            "label": "PRJ-001 Marina Tower C (dubai_municipality)",
            "facts": facts, "allowed": agents.expand_evidence(facts)}


# --- pure extraction ---------------------------------------------------------

def test_authority_references_are_read_bracketed_or_not():
    found = agents.references_in("see BP-2026-9902 and [DEWA-2026-5510]")
    assert {"BP-2026-9902", "DEWA-2026-5510"} <= found


def test_a_hyphenated_word_is_not_read_as_a_reference():
    assert agents.references_in("the AS-BUILT drawings and FIRE-SAFETY plan") == set()


def test_only_iso_dates_are_read_as_dates():
    assert agents.dates_in("file by 2026-10-05, roughly mid-October") == {"2026-10-05"}


# --- what counts as evidence -------------------------------------------------

def test_the_projects_own_references_are_citable():
    allowed = agents.expand_evidence(_facts())
    assert {"BP-2026-9902", "DEWA-2026-5510", "DCD-2026-8812"} <= allowed["references"]


def test_computed_dates_are_citable():
    allowed = agents.expand_evidence(_facts())
    assert TODAY.isoformat() in allowed["dates"]
    assert len(allowed["dates"]) > 1, "forecast dates should be licensed too"


def test_a_will_bounce_approval_is_in_the_unfilable_set():
    allowed = agents.expand_evidence(_facts())
    assert "BUILDING_PERMIT" in allowed["unfilable"]


# --- orchestration -----------------------------------------------------------

class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Resp:
    def __init__(self, payload, stop_reason="end_turn"):
        self.stop_reason = stop_reason
        self.content = [_Block(json.dumps(payload))]


class FakeMessages:
    def __init__(self, explain, actions, review, explode=(), stop_reason="end_turn"):
        self.payloads = {"explain": explain, "actions": actions, "review": review}
        self.explode = set(explode)
        self.stop_reason = stop_reason
        self.calls = []
        self.kwargs = []

    def create(self, **kw):
        # Route by schema shape, not by grepping the system prompt -- a
        # wrapped docstring can silently split a matched phrase across two
        # lines, and the schema is what actually determines the role.
        props = set(kw["output_config"]["format"]["schema"]["properties"])
        if "recommendation" in props:
            role = "review"
        elif "actions" in props:
            role = "actions"
        else:
            role = "explain"
        self.calls.append(role)
        self.kwargs.append(kw)
        if role in self.explode:
            raise RuntimeError("simulated API failure")
        return _Resp(self.payloads[role], stop_reason=self.stop_reason)


def _install(msgs):
    # The real call is client.beta.messages.create, so the stub has to nest
    # the same way or the request-shape tests below pass against nothing.
    beta = type("B", (), {"messages": msgs})()
    agents._client = lambda: type("C", (), {"beta": beta})()  # noqa: SLF001
    return msgs


def _explain(text="The building permit is with the authority but DEWA_NOC has "
                  "not been granted, so it will be rejected on sequence."):
    return {"explanation": text}


def _actions(text="Chase DEWA on DEWA-2026-5510. Do not expect BP-2026-9902 "
                  "to progress until that clears."):
    return {"actions": text}


def _review(recommendation="release",
            rationale="The position on BP-2026-9902 is correctly stated."):
    return {"recommendation": recommendation, "rationale": rationale}


def _run_and_gate(msgs):
    _install(msgs)
    t = _task()
    [out] = agents.run([t], workers=1)
    agents.gate(out, out["allowed"])
    return out


def test_a_clean_draft_passes_all_three_checks():
    out = _run_and_gate(FakeMessages(_explain(), _actions(), _review()))
    assert out["status"] == "released", out.get("status_reason")


def test_an_invented_reference_forces_a_hold():
    out = _run_and_gate(FakeMessages(
        _explain(), _actions("Cross-check against permit BP-2026-0001."),
        _review()))
    assert out["status"] == "held"
    assert "BP-2026-0001" in out["status_reason"]


def test_an_invented_date_forces_a_hold():
    """The headline case. Every reference is real, the recommendation is
    confident, the sentence is well-formed -- and 2026-10-31 is a date no
    computation produced. A wrong date does not look wrong."""
    out = _run_and_gate(FakeMessages(
        _explain(), _actions("Expect DEWA-2026-5510 to clear by 2026-10-31."),
        _review()))
    assert out["status"] == "held", out.get("status_reason")
    assert "2026-10-31" in out["status_reason"]


def test_a_computed_date_passes():
    facts = _facts()
    some_date = sorted(agents.expand_evidence(facts)["dates"])[-1]
    out = _run_and_gate(FakeMessages(
        _explain(), _actions(f"Earliest realistic movement is {some_date}."),
        _review()))
    assert out["status"] == "released", out.get("status_reason")


def test_urging_a_filing_the_engine_marked_unfilable_forces_a_hold():
    """The engine owns readiness. A model that reads a WILL_BOUNCE approval's
    reasons and concludes 'file it anyway' is overruling a computation."""
    out = _run_and_gate(FakeMessages(
        _explain(),
        _actions("Submit BUILDING_PERMIT now to save a cycle."),
        _review()))
    assert out["status"] == "held", out.get("status_reason")
    assert "BUILDING_PERMIT" in out["status_reason"]


def test_merely_naming_an_unfilable_approval_is_allowed():
    """The check fires on urging a filing, not on discussing the approval --
    otherwise the gate would hold every accurate explanation."""
    out = _run_and_gate(FakeMessages(
        _explain(),
        _actions("BUILDING_PERMIT is waiting on DEWA_NOC and cannot progress."),
        _review()))
    assert out["status"] == "released", out.get("status_reason")


def test_a_hold_recommendation_is_gated_to_held():
    out = _run_and_gate(FakeMessages(
        _explain(), _actions(),
        _review(recommendation="hold", rationale="Position needs verifying.")))
    assert out["status"] == "held"
    assert "recommended holding" in out["status_reason"]


def test_the_gate_cannot_turn_a_hold_into_a_release():
    """The gate only ever pushes toward holding -- there is no branch that
    releases advice the reviewer did not itself recommend releasing."""
    out = _run_and_gate(FakeMessages(_explain(), _actions(),
                                     _review(recommendation="hold")))
    assert out["status"] == "held"


def test_any_agent_failure_holds():
    for role in ("explain", "actions", "review"):
        out = _run_and_gate(FakeMessages(_explain(), _actions(), _review(),
                                         explode=(role,)))
        assert out["status"] == "held", f"{role} failure did not hold"


def test_the_checks_run_in_order_of_severity():
    """A draft that invents a reference and a date is reported on the
    reference -- the first thing an engineer would go and look for."""
    out = _run_and_gate(FakeMessages(
        _explain(),
        _actions("Per BP-2026-0001, expect clearance 2026-10-31."),
        _review()))
    assert "BP-2026-0001" in out["status_reason"]
    assert "2026-10-31" not in out["status_reason"]


# --- request shape (the token-budget lesson, enforced here) -----------------

def test_token_budget_leaves_room_for_thinking():
    """Thinking is on by default on this model and counts against max_tokens.
    A budget tight enough to truncate the JSON surfaces as a parse error,
    which the gate turns into a hold -- every project would hold and it would
    look like the gate correctly failing safe rather than the budget being
    wrong."""
    assert agents.MAX_TOKENS >= 8000, (
        f"MAX_TOKENS={agents.MAX_TOKENS} risks truncating the reply mid-JSON")
    msgs = _install(FakeMessages(_explain(), _actions(), _review()))
    agents.run([_task()], workers=1)
    for kw in msgs.kwargs:
        assert kw["max_tokens"] == agents.MAX_TOKENS


def test_a_truncated_reply_is_named_not_reported_as_a_parse_error():
    _install(FakeMessages(_explain(), _actions(), _review(),
                          stop_reason="max_tokens"))
    try:
        agents.run([_task()], workers=1)
    except agents.AgentUnavailable as exc:
        assert "token cap" in str(exc), exc
    else:
        raise AssertionError("a truncated reply was not surfaced")


def test_structured_request_shape_is_what_the_api_expects():
    msgs = _install(FakeMessages(_explain(), _actions(), _review()))
    agents.run([_task()], workers=1)
    assert msgs.calls == ["explain", "actions", "review"]
    for kw in msgs.kwargs:
        cfg = kw["output_config"]
        assert cfg["format"]["type"] == "json_schema"
        assert cfg["format"]["schema"]["additionalProperties"] is False
        assert cfg["effort"] in ("low", "medium", "high", "xhigh", "max")
        assert "effort" not in kw, "effort belongs inside output_config"
    # The reviewer is the highest-stakes step and runs at high effort.
    assert msgs.kwargs[2]["output_config"]["effort"] == "high"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  pass  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL  {name}: {exc}")
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)
