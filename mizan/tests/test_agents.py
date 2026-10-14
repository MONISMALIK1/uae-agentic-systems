"""The Claim Gate, against a stubbed client.

The check this file exists for is `check_overclaim()`, which is a different
shape from the membership checks in the other systems here. Those ask *is
this figure in the evidence set?*. This one asks *is this figure larger than
the evidence permits?* -- a bound, not a lookup.

That matters because the characteristic failure of a billing claim is not
inventing a number from nothing. It is rounding a defensible number upward
until the whole claim becomes contestable.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date  # noqa: E402

from mizan import agents, rules, units  # noqa: E402
from mizan.config import PEAK_MONTHS, Config  # noqa: E402

TODAY = date(2026, 12, 1)


def _full_year(unit_id, peak):
    out = []
    for y, m in [(2026, i) for i in range(1, 13)] + [(2025, 11), (2025, 12)]:
        out.append(units.Reading(unit_id, f"{y}-{m:02d}",
                                 peak if m in PEAK_MONTHS else peak * 0.4,
                                 peak * 400))
    return out


def _portfolio():
    """One claimable unit, one with insufficient evidence."""
    unit_rows = [
        units.Unit("UNT-0101", "Marina Heights", "retail", 45.0, 3200.0, "OWN-5501"),
        units.Unit("UNT-0104", "Marina Heights", "storage", 18.0, 3200.0, "OWN-5504"),
    ]
    reading_rows = _full_year("UNT-0101", 18.0) + [
        units.Reading("UNT-0104", "2026-01", 6.0, 2400.0),
        units.Reading("UNT-0104", "2026-02", 5.8, 2300.0),
    ]
    return rules.assess(unit_rows, reading_rows, Config(), TODAY)


def _task():
    pf = _portfolio()
    facts = pf.facts()
    blocked = [f.unit_id for f in pf.by_state("INSUFFICIENT_EVIDENCE")]
    return {"review_id": TODAY.isoformat(), "label": "1 claimable unit",
            "facts": facts,
            "allowed": agents.expand_evidence(facts, blocked_units=blocked)}


def _ceiling():
    return _task()["allowed"]["ceiling"]


# --- pure extraction ---------------------------------------------------------

def test_identifiers_are_read():
    assert {"UNT-0101", "OWN-5501"} <= agents.citations_in(
        "unit UNT-0101 held by OWN-5501")


def test_a_hyphenated_word_is_not_an_identifier():
    assert agents.citations_in("the CHILLED-WATER and SUB-METER records") == set()


def test_claim_amounts_are_recognised_in_either_order():
    assert 225600.0 in agents.claim_amounts_in("recover 225,600.00 AED")
    assert 225600.0 in agents.claim_amounts_in("225,600.00 AED should be refunded")


def test_a_figure_not_presented_as_a_claim_is_not_a_claim_amount():
    """Mentioning an allocation is not asking for it back."""
    assert agents.claim_amounts_in("the unit is allocated 45 RT") == set()


# --- the overclaim check, in isolation ---------------------------------------

def test_claiming_at_the_ceiling_is_allowed():
    ceiling = _ceiling()
    assert agents.check_overclaim(f"recover {ceiling:,.2f} AED", ceiling, set()) == []


def test_claiming_above_the_ceiling_is_an_overclaim():
    ceiling = _ceiling()
    out = agents.check_overclaim(f"recover {ceiling + 50_000:,.2f} AED",
                                 ceiling, set())
    assert out and "against a computed ceiling" in out[0]


def test_claim_language_about_a_blocked_unit_is_an_overclaim():
    """The engine refused to make a finding. The drafting layer may not
    manufacture one."""
    out = agents.check_overclaim(
        "UNT-0104 is also over-allocated and a refund is due",
        _ceiling(), {"UNT-0104"})
    assert out and "UNT-0104" in out[0]
    assert "insufficient" in out[0]


def test_describing_a_blocked_unit_without_claiming_is_allowed():
    """Saying the evidence is thin must pass, or the gate would hold every
    honest account."""
    assert agents.check_overclaim(
        "UNT-0104 has only two months of data and needs a full season",
        _ceiling(), {"UNT-0104"}) == []


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
    def __init__(self, explain, claim, review, explode=(), stop_reason="end_turn"):
        self.payloads = {"explain": explain, "claim": claim, "review": review}
        self.explode = set(explode)
        self.stop_reason = stop_reason
        self.calls = []
        self.kwargs = []

    def create(self, **kw):
        props = set(kw["output_config"]["format"]["schema"]["properties"])
        if "recommendation" in props:
            role = "review"
        elif "claim" in props:
            role = "claim"
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


def _explain(text="UNT-0101 is allocated well above its observed peak across "
                  "a full season."):
    return {"explanation": text}


def _claim(text=None):
    if text is None:
        text = (f"For UNT-0101 we seek recovery of {_ceiling():,.2f} AED, "
                f"measured against observed peak demand plus headroom.")
    return {"claim": text}


def _review(recommendation="release",
            rationale="The position on UNT-0101 is measured and bounded."):
    return {"recommendation": recommendation, "rationale": rationale}


def _run_and_gate(msgs):
    _install(msgs)
    t = _task()
    [out] = agents.run([t], workers=1)
    agents.gate(out, out["allowed"])
    return out


def test_a_claim_at_the_ceiling_passes():
    out = _run_and_gate(FakeMessages(_explain(), _claim(), _review()))
    assert out["status"] == "released", out.get("status_reason")


def test_a_claim_above_the_ceiling_is_held():
    """The headline case. Every unit is real, the direction is right, the
    evidence is sound -- and the figure has been rounded up past what the
    evidence supports."""
    inflated = _ceiling() + 75_000
    out = _run_and_gate(FakeMessages(
        _explain(), _claim(f"We seek recovery of {inflated:,.2f} AED on UNT-0101."),
        _review()))
    assert out["status"] == "held", out.get("status_reason")
    assert "ceiling" in out["status_reason"]


def test_claiming_for_a_unit_with_insufficient_evidence_is_held():
    out = _run_and_gate(FakeMessages(
        _explain(),
        _claim("UNT-0101 and UNT-0104 are both over-allocated; a refund is due "
               "on each."),
        _review()))
    assert out["status"] == "held"
    assert "UNT-0104" in out["status_reason"]


def test_an_invented_unit_is_held():
    out = _run_and_gate(FakeMessages(
        _explain(), _claim("UNT-7777 is also over-allocated."), _review()))
    assert out["status"] == "held"
    assert "UNT-7777" in out["status_reason"]


def test_an_invented_figure_is_held():
    out = _run_and_gate(FakeMessages(
        _explain(), _claim("The excess measured 99.9 RT on UNT-0101."), _review()))
    assert out["status"] == "held"


def test_overclaim_is_checked_before_bare_figures():
    """A draft that both overclaims and invents a stray figure is reported on
    the overclaim -- it is the failure that loses the case."""
    inflated = _ceiling() + 75_000
    out = _run_and_gate(FakeMessages(
        _explain(),
        _claim(f"Recover {inflated:,.2f} AED; the excess measured 99.9 RT."),
        _review()))
    assert "ceiling" in out["status_reason"]


def test_a_hold_recommendation_is_gated_to_held():
    out = _run_and_gate(FakeMessages(
        _explain(), _claim(),
        _review(recommendation="hold", rationale="Evidence window is thin.")))
    assert out["status"] == "held"
    assert "recommended holding" in out["status_reason"]


def test_the_gate_cannot_turn_a_hold_into_a_release():
    out = _run_and_gate(FakeMessages(_explain(), _claim(),
                                     _review(recommendation="hold")))
    assert out["status"] == "held"


def test_any_agent_failure_holds():
    for role in ("explain", "claim", "review"):
        out = _run_and_gate(FakeMessages(_explain(), _claim(), _review(),
                                         explode=(role,)))
        assert out["status"] == "held", f"{role} failure did not hold"


# --- request shape -----------------------------------------------------------

def test_token_budget_leaves_room_for_thinking():
    assert agents.MAX_TOKENS >= 8000
    msgs = _install(FakeMessages(_explain(), _claim(), _review()))
    agents.run([_task()], workers=1)
    for kw in msgs.kwargs:
        assert kw["max_tokens"] == agents.MAX_TOKENS


def test_a_truncated_reply_is_named_not_reported_as_a_parse_error():
    _install(FakeMessages(_explain(), _claim(), _review(),
                          stop_reason="max_tokens"))
    try:
        agents.run([_task()], workers=1)
    except agents.AgentUnavailable as exc:
        assert "token cap" in str(exc), exc
    else:
        raise AssertionError("a truncated reply was not surfaced")


def test_structured_request_shape_is_what_the_api_expects():
    msgs = _install(FakeMessages(_explain(), _claim(), _review()))
    agents.run([_task()], workers=1)
    assert msgs.calls == ["explain", "claim", "review"]
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
