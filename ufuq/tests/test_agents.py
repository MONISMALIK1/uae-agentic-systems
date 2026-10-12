"""The Assurance Gate, against a stubbed client.

The check this file exists for is `check_reassurance()`: a company the engine
computed as in breach must not be told it is on track. That is this system's
characteristic failure -- not a wrong number, but false comfort, which
produces no action and no alarm until a deadline that was already unreachable.

The tests also pin the limitation honestly: the check is a keyword test, it
is evadable, and `test_the_keyword_check_is_evadable_by_construction`
documents that rather than pretending otherwise.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date  # noqa: E402

from ufuq import agents, roster, rules  # noqa: E402
from ufuq.config import Config  # noqa: E402

TODAY = date(2026, 11, 1)


def _facts(skilled=180, emirati=9):
    """Real evidence from a real projection. Defaults to a locked breach."""
    snap = roster.Snapshot(company_id="CO-1002",
                           company_name="Arabian Facilities Co",
                           as_of=date(2026, 9, 1), skilled_roles=skilled,
                           emirati_skilled=emirati)
    events = [roster.Event("CO-1002", "REQ-20201", "hire", "sourcing",
                           True, True, date(2026, 12, 1))]
    return rules.assess(snap, events, Config(), TODAY).facts()


def _task(skilled=180, emirati=9):
    facts = _facts(skilled, emirati)
    return {"company_id": "CO-1002",
            "label": "CO-1002 Arabian Facilities Co",
            "facts": facts, "allowed": agents.expand_evidence(facts)}


# --- pure extraction ---------------------------------------------------------

def test_identifiers_are_read_bracketed_or_not():
    assert {"REQ-20201", "CO-1002"} <= agents.citations_in(
        "open REQ-20201 for [CO-1002]")


def test_a_hyphenated_word_is_not_read_as_an_identifier():
    assert agents.citations_in("a NON-EMIRATI SKILLED-ROLE hire") == set()


def test_dates_are_not_double_counted_as_figures():
    """2026-12-31 is a date, not three numbers."""
    assert agents.numbers_in("by 2026-12-31") == set()


def test_identifier_digits_are_not_read_as_figures():
    assert agents.numbers_in("under REQ-20201") == set()


# --- what counts as evidence -------------------------------------------------

def test_a_breach_company_is_marked_in_breach():
    allowed = agents.expand_evidence(_facts())
    assert allowed["in_breach"] is True


def test_a_compliant_company_is_not_marked_in_breach():
    allowed = agents.expand_evidence(_facts(skilled=240, emirati=40))
    assert allowed["in_breach"] is False


def test_computed_figures_and_dates_are_licensed():
    allowed = agents.expand_evidence(_facts())
    assert allowed["numbers"], "figures should be licensed"
    assert any(d.startswith("2026-") for d in allowed["dates"])


# --- the reassurance check, in isolation -------------------------------------

def test_reassuring_language_is_caught_for_a_company_in_breach():
    for phrase in ("the company is compliant",
                   "you are on track",
                   "no action is required",
                   "this meets the target",
                   "comfortably positioned",
                   "the position is safe"):
        assert agents.check_reassurance(phrase, in_breach=True), phrase


def test_the_same_language_is_permitted_for_a_company_not_in_breach():
    assert agents.check_reassurance("the company is compliant",
                                    in_breach=False) == []


def test_naming_the_shortfall_is_not_reassurance():
    """Talking about a compliance *gap* must not trip the filter, or the gate
    would hold every accurate description of a breach."""
    assert agents.check_reassurance(
        "there is a compliance gap of four roles", in_breach=True) == []
    assert agents.check_reassurance(
        "this is a compliance breach", in_breach=True) == []


def test_the_keyword_check_is_evadable_by_construction():
    """Documented, not hidden. A model writing around the keywords passes the
    filter. The architectural guarantee is that report.py prints the engine's
    verdict above any drafted text -- see docs/the-assurance-gate.md."""
    evasive = "Your position for this year looks perfectly fine as it stands."
    assert agents.check_reassurance(evasive, in_breach=True) == []


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
    def __init__(self, explain, plan, review, explode=(), stop_reason="end_turn"):
        self.payloads = {"explain": explain, "plan": plan, "review": review}
        self.explode = set(explode)
        self.stop_reason = stop_reason
        self.calls = []
        self.kwargs = []

    def create(self, **kw):
        props = set(kw["output_config"]["format"]["schema"]["properties"])
        if "recommendation" in props:
            role = "review"
        elif "plan" in props:
            role = "plan"
        else:
            role = "explain"
        self.calls.append(role)
        self.kwargs.append(kw)
        if role in self.explode:
            raise RuntimeError("simulated API failure")
        return _Resp(self.payloads[role], stop_reason=self.stop_reason)


def _install(msgs):
    beta = type("B", (), {"messages": msgs})()
    agents._client = lambda: type("C", (), {"beta": beta})()  # noqa: SLF001
    return msgs


def _explain(text="The company is short on accepted offers for this year and "
                  "the hiring runway has closed."):
    return {"explanation": text}


def _plan(text="Open requisitions under REQ-20201 for next year; this year's "
                "shortfall must be budgeted rather than hired away."):
    return {"plan": text}


def _review(recommendation="release",
            rationale="The shortfall on REQ-20201 is stated plainly."):
    return {"recommendation": recommendation, "rationale": rationale}


def _run_and_gate(msgs, skilled=180, emirati=9):
    _install(msgs)
    t = _task(skilled, emirati)
    [out] = agents.run([t], workers=1)
    agents.gate(out, out["allowed"])
    return out


def test_a_clean_draft_passes():
    out = _run_and_gate(FakeMessages(_explain(), _plan(), _review()))
    assert out["status"] == "released", out.get("status_reason")


def test_reassuring_a_company_in_breach_forces_a_hold():
    """The headline case. Every identifier is real, the figures are real, the
    recommendation is confident -- and the company is being told it is fine
    when the engine computed a locked breach."""
    out = _run_and_gate(FakeMessages(
        _explain("The company is on track and no action is required."),
        _plan(), _review()))
    assert out["status"] == "held", out.get("status_reason")
    assert "on track" in out["status_reason"]


def test_the_same_phrasing_passes_for_a_compliant_company():
    out = _run_and_gate(FakeMessages(
        _explain("The company is on track and no action is required."),
        _plan("Maintain the current pipeline."), _review()),
        skilled=240, emirati=40)
    assert out["status"] == "released", out.get("status_reason")


def test_an_invented_requisition_forces_a_hold():
    out = _run_and_gate(FakeMessages(
        _explain(), _plan("Convert REQ-99999 to an offer."), _review()))
    assert out["status"] == "held"
    assert "REQ-99999" in out["status_reason"]


def test_an_invented_date_forces_a_hold():
    out = _run_and_gate(FakeMessages(
        _explain(), _plan("Requisitions must open by 2027-03-14."), _review()))
    assert out["status"] == "held"
    assert "2027-03-14" in out["status_reason"]


def test_an_invented_figure_forces_a_hold():
    out = _run_and_gate(FakeMessages(
        _explain(), _plan("The shortfall is 37 roles."), _review()))
    assert out["status"] == "held"
    assert "37" in out["status_reason"]


def test_reassurance_is_checked_before_figures():
    """A draft that both reassures and invents a figure is reported on the
    reassurance -- it is the failure that produces no alarm."""
    out = _run_and_gate(FakeMessages(
        _explain("You are on track; the shortfall is 37 roles."),
        _plan(), _review()))
    assert "on track" in out["status_reason"]
    assert "37" not in out["status_reason"]


def test_a_hold_recommendation_is_gated_to_held():
    out = _run_and_gate(FakeMessages(
        _explain(), _plan(),
        _review(recommendation="hold", rationale="Plan understates the gap.")))
    assert out["status"] == "held"
    assert "recommended holding" in out["status_reason"]


def test_the_gate_cannot_turn_a_hold_into_a_release():
    out = _run_and_gate(FakeMessages(_explain(), _plan(),
                                     _review(recommendation="hold")))
    assert out["status"] == "held"


def test_any_agent_failure_holds():
    for role in ("explain", "plan", "review"):
        out = _run_and_gate(FakeMessages(_explain(), _plan(), _review(),
                                         explode=(role,)))
        assert out["status"] == "held", f"{role} failure did not hold"


# --- request shape -----------------------------------------------------------

def test_token_budget_leaves_room_for_thinking():
    assert agents.MAX_TOKENS >= 8000, (
        f"MAX_TOKENS={agents.MAX_TOKENS} risks truncating the reply mid-JSON")
    msgs = _install(FakeMessages(_explain(), _plan(), _review()))
    agents.run([_task()], workers=1)
    for kw in msgs.kwargs:
        assert kw["max_tokens"] == agents.MAX_TOKENS


def test_a_truncated_reply_is_named_not_reported_as_a_parse_error():
    _install(FakeMessages(_explain(), _plan(), _review(),
                          stop_reason="max_tokens"))
    try:
        agents.run([_task()], workers=1)
    except agents.AgentUnavailable as exc:
        assert "token cap" in str(exc), exc
    else:
        raise AssertionError("a truncated reply was not surfaced")


def test_structured_request_shape_is_what_the_api_expects():
    msgs = _install(FakeMessages(_explain(), _plan(), _review()))
    agents.run([_task()], workers=1)
    assert msgs.calls == ["explain", "plan", "review"]
    for kw in msgs.kwargs:
        cfg = kw["output_config"]
        assert cfg["format"]["type"] == "json_schema"
        assert cfg["format"]["schema"]["additionalProperties"] is False
        assert cfg["effort"] in ("low", "medium", "high", "xhigh", "max")
        assert "effort" not in kw, "effort belongs inside output_config"
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
