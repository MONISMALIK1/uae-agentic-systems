"""The Attribution Gate, against a stubbed client.

Three checks. The one this file exists for is `check_naming()`: the engine's
refusal to name somebody it could not establish must be unforgeable by the
drafting layer. A model that reads a contested fine's reasons -- which list
the candidate assignments by ID -- and infers a driver from them has turned a
"we don't know" into an accusation.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date, datetime  # noqa: E402

from athar import agents, assignments, fines, rules  # noqa: E402
from athar.config import Config  # noqa: E402

TODAY = date(2026, 9, 22)


def _ledger():
    """A real ledger with one attributed fine and one contested one."""
    fine_rows = [
        # Clean interior hit on ASG-00101 -> attributed to DRV-4401.
        fines.Fine(fine_id="FN-00005", plate="C55019",
                   issued_at=datetime(2026, 9, 12, 23, 15),
                   received_at=date(2026, 9, 20), source="dubai_police",
                   location="Jumeirah", amount_aed=3000.0, black_points=8),
        # Overlapping custody -> contested, nobody named.
        fines.Fine(fine_id="FN-00011", plate="G20044",
                   issued_at=datetime(2026, 9, 17, 5, 45),
                   received_at=date(2026, 9, 22), source="dubai_police",
                   location="Airport Tunnel", amount_aed=1500.0, black_points=4),
    ]
    asg_rows = [
        assignments.Assignment("ASG-00301", "C55019", "DRV-6620", "R. Fernandes",
                               "shift", datetime(2026, 9, 12, 18, 0),
                               datetime(2026, 9, 13, 6, 0), "", ""),
        assignments.Assignment("ASG-00601", "G20044", "DRV-9950", "N. Rahman",
                               "rental", datetime(2026, 9, 17, 5, 0),
                               datetime(2026, 9, 17, 9, 0), "RC-2026-9402",
                               "HO-2026-3610"),
        assignments.Assignment("ASG-00602", "G20044", "DRV-9951", "B. Suleiman",
                               "rental", datetime(2026, 9, 17, 5, 30),
                               datetime(2026, 9, 17, 12, 0), "RC-2026-9403",
                               "HO-2026-3611"),
    ]
    return rules.assess(fine_rows, asg_rows, Config(), TODAY), asg_rows


def _facts():
    ledger, asg_rows = _ledger()
    facts = ledger.facts()
    facts["fleet_driver_ids"] = sorted({a.driver_id for a in asg_rows})
    return facts


def _task():
    facts = _facts()
    return {"batch_id": TODAY.isoformat(), "label": "2 actionable fines",
            "facts": facts, "allowed": agents.expand_evidence(facts)}


# --- pure extraction ---------------------------------------------------------

def test_identifiers_are_read_bracketed_or_not():
    found = agents.citations_in("see FN-00005 and [ASG-00301]")
    assert {"FN-00005", "ASG-00301"} <= found


def test_a_hyphenated_word_is_not_read_as_an_identifier():
    assert agents.citations_in("the vehicle was OFF-HIRE and NON-RECOVERABLE") == set()


def test_the_digits_inside_an_identifier_are_not_read_as_a_figure():
    assert agents.numbers_in("cited ASG-00301") == set()


# --- what counts as evidence -------------------------------------------------

def test_the_attributed_driver_is_citable():
    allowed = agents.expand_evidence(_facts())
    assert "DRV-6620" in allowed["citations"]


def test_drivers_the_engine_declined_to_attribute_are_unnameable():
    """Both candidates on the contested fine are real people in the fleet.
    That is exactly why they must not be named: the name is real, it is the
    attribution that is not established."""
    allowed = agents.expand_evidence(_facts())
    assert {"DRV-9950", "DRV-9951"} <= allowed["unnameable"]
    assert "DRV-6620" not in allowed["unnameable"]


def test_computed_figures_are_licensed():
    allowed = agents.expand_evidence(_facts())
    assert 3000.0 in allowed["numbers"]


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
    def __init__(self, explain, notice, review, explode=(), stop_reason="end_turn"):
        self.payloads = {"explain": explain, "notice": notice, "review": review}
        self.explode = set(explode)
        self.stop_reason = stop_reason
        self.calls = []
        self.kwargs = []

    def create(self, **kw):
        # Route by schema shape, not by grepping the system prompt -- a
        # wrapped docstring can split a matched phrase across two lines.
        props = set(kw["output_config"]["format"]["schema"]["properties"])
        if "recommendation" in props:
            role = "review"
        elif "notice" in props:
            role = "notice"
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


def _explain(text="FN-00005 matched a single custody interval. FN-00011 fell "
                  "across two overlapping records and could not be settled."):
    return {"explanation": text}


def _notice(text="Recover FN-00005 via ASG-00301 as an employee conversation. "
                 "For FN-00011, retrieve the handover timestamps before acting."):
    return {"notice": text}


def _review(recommendation="release",
            rationale="FN-00005 is clean; FN-00011 is correctly left open."):
    return {"recommendation": recommendation, "rationale": rationale}


def _run_and_gate(msgs):
    _install(msgs)
    t = _task()
    [out] = agents.run([t], workers=1)
    agents.gate(out, out["allowed"])
    return out


def test_a_clean_draft_passes_all_three_checks():
    out = _run_and_gate(FakeMessages(_explain(), _notice(), _review()))
    assert out["status"] == "released", out.get("status_reason")


def test_naming_a_driver_on_a_contested_fine_forces_a_hold():
    """The headline case. DRV-9950 is a real person who really did rent that
    car -- and the engine could not establish that they were driving at the
    moment of the violation. Naming them is an accusation the data does not
    support."""
    out = _run_and_gate(FakeMessages(
        _explain(),
        _notice("For FN-00011, charge DRV-9950, who collected the vehicle first."),
        _review()))
    assert out["status"] == "held", out.get("status_reason")
    assert "DRV-9950" in out["status_reason"]


def test_naming_the_other_candidate_is_equally_held():
    out = _run_and_gate(FakeMessages(
        _explain("FN-00011 was most likely DRV-9951 given the timing."),
        _notice(), _review()))
    assert out["status"] == "held"
    assert "DRV-9951" in out["status_reason"]


def test_describing_a_contested_fine_without_naming_anyone_is_allowed():
    """The check is scoped to identifiers, not prose. Saying 'the renter' about
    a contested fine is honest and must pass."""
    out = _run_and_gate(FakeMessages(
        _explain(),
        _notice("For FN-00011, ask whoever held the vehicle that morning to "
                "confirm; do not charge anyone until the records agree."),
        _review()))
    assert out["status"] == "released", out.get("status_reason")


def test_naming_the_attributed_driver_is_allowed():
    out = _run_and_gate(FakeMessages(
        _explain(), _notice("Raise FN-00005 with DRV-6620 under ASG-00301."),
        _review()))
    assert out["status"] == "released", out.get("status_reason")


def test_an_invented_identifier_forces_a_hold():
    out = _run_and_gate(FakeMessages(
        _explain(), _notice("Cross-check against contract RC-2026-0000."),
        _review()))
    assert out["status"] == "held"
    assert "RC-2026-0000" in out["status_reason"]


def test_an_invented_figure_forces_a_hold():
    out = _run_and_gate(FakeMessages(
        _explain(), _notice("Total exposure this batch is 4,500.00 AED."),
        _review()))
    assert out["status"] == "held"
    assert "4,500" in out["status_reason"]


def test_a_hold_recommendation_is_gated_to_held():
    out = _run_and_gate(FakeMessages(
        _explain(), _notice(),
        _review(recommendation="hold", rationale="Evidence incomplete.")))
    assert out["status"] == "held"
    assert "recommended holding" in out["status_reason"]


def test_the_gate_cannot_turn_a_hold_into_a_release():
    out = _run_and_gate(FakeMessages(_explain(), _notice(),
                                     _review(recommendation="hold")))
    assert out["status"] == "held"


def test_any_agent_failure_holds():
    for role in ("explain", "notice", "review"):
        out = _run_and_gate(FakeMessages(_explain(), _notice(), _review(),
                                         explode=(role,)))
        assert out["status"] == "held", f"{role} failure did not hold"


def test_naming_is_checked_before_figures():
    """A draft that both names someone and invents a figure is reported on the
    naming -- it is the more serious of the two by a wide margin."""
    out = _run_and_gate(FakeMessages(
        _explain(),
        _notice("Charge DRV-9950 the 4,500.00 AED balance."),
        _review()))
    assert "DRV-9950" in out["status_reason"]
    assert "4,500" not in out["status_reason"]


# --- request shape -----------------------------------------------------------

def test_token_budget_leaves_room_for_thinking():
    assert agents.MAX_TOKENS >= 8000, (
        f"MAX_TOKENS={agents.MAX_TOKENS} risks truncating the reply mid-JSON")
    msgs = _install(FakeMessages(_explain(), _notice(), _review()))
    agents.run([_task()], workers=1)
    for kw in msgs.kwargs:
        assert kw["max_tokens"] == agents.MAX_TOKENS


def test_a_truncated_reply_is_named_not_reported_as_a_parse_error():
    _install(FakeMessages(_explain(), _notice(), _review(),
                          stop_reason="max_tokens"))
    try:
        agents.run([_task()], workers=1)
    except agents.AgentUnavailable as exc:
        assert "token cap" in str(exc), exc
    else:
        raise AssertionError("a truncated reply was not surfaced")


def test_structured_request_shape_is_what_the_api_expects():
    msgs = _install(FakeMessages(_explain(), _notice(), _review()))
    agents.run([_task()], workers=1)
    assert msgs.calls == ["explain", "notice", "review"]
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
