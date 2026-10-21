"""Structural guarantees of the workflow definition.

The cost-safety rule ("never leave a temporary instance running") lives in the
state machine's wiring, so these tests check the wiring itself.
"""
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFINITION = json.loads((ROOT / "statemachine" / "restorecheck.asl.json").read_text())
STATES = DEFINITION["States"]
TERMINAL_TYPES = {"Succeed", "Fail"}


def successors(state):
    nxt = [state["Next"]] if "Next" in state else []
    nxt += [choice["Next"] for choice in state.get("Choices", [])]
    nxt += [state["Default"]] if "Default" in state else []
    nxt += [catch["Next"] for catch in state.get("Catch", [])]
    return nxt


def is_terminal(state):
    return state.get("End", False) or state["Type"] in TERMINAL_TYPES


def test_every_reference_points_at_a_real_state():
    assert DEFINITION["StartAt"] in STATES
    for name, state in STATES.items():
        for target in successors(state):
            assert target in STATES, f"{name} -> {target}"


@pytest.mark.parametrize(
    "name",
    [n for n, s in STATES.items() if s["Type"] == "Task" and n not in ("Teardown", "RecordResult")],
)
def test_every_step_before_teardown_routes_failures_to_teardown(name):
    catches = STATES[name].get("Catch", [])
    assert any(
        c["ErrorEquals"] == ["States.ALL"] and c["Next"] == "Teardown" for c in catches
    ), f"{name} can fail without tearing down the temporary instance"


def test_no_path_ends_the_run_without_passing_teardown():
    seen, frontier = set(), [DEFINITION["StartAt"]]
    while frontier:
        name = frontier.pop()
        if name in seen or name == "Teardown":
            continue
        seen.add(name)
        assert not is_terminal(STATES[name]), f"{name} ends the run before Teardown"
        frontier.extend(successors(STATES[name]))


def test_teardown_always_leads_to_recording_the_result():
    teardown = STATES["Teardown"]
    assert teardown["Next"] == "RecordResult"
    assert [c["Next"] for c in teardown["Catch"]] == ["RecordResult"]
    assert teardown["Catch"][0]["ErrorEquals"] == ["States.ALL"]


def test_catch_all_retriers_come_last_and_alone():
    # An ASL rule: States.ALL must be alone in its retrier and be the last one.
    for name, state in STATES.items():
        retriers = state.get("Retry", [])
        for i, retrier in enumerate(retriers):
            if "States.ALL" in retrier["ErrorEquals"]:
                assert retrier["ErrorEquals"] == ["States.ALL"], name
                assert i == len(retriers) - 1, name


def test_placeholders_match_template_substitutions():
    class CfnLoader(yaml.SafeLoader):
        pass

    # Ignore CloudFormation's !Ref / !GetAtt / !Sub tags; only the keys matter here.
    CfnLoader.add_multi_constructor("!", lambda loader, suffix, node: None)
    template = yaml.load((ROOT / "template.yaml").read_text(), Loader=CfnLoader)
    substitutions = template["Resources"]["VerificationStateMachine"]["Properties"][
        "DefinitionSubstitutions"
    ]

    placeholders = set(re.findall(r"\$\{(\w+)\}", json.dumps(DEFINITION)))

    assert placeholders == set(substitutions)
