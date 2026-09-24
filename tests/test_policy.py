import ast
import copy
import pytest
from conftest import ScriptedClient
from jev_fle.policy import TypedPolicy, entity_refs, check_program, inventory

SKILLS = [
    ("Inspect an item", "inspect_recipe"), ("Locate the nearest", "locate"),
    ("Allow one second", "wait"), ("Place one structure", "place"),
    ("Place a structure directly", "adjacent"), ("Rotate an observed", "rotate"),
    ("Recover an observed", "remove"), ("Extract a bounded", "extract"),
    ("Insert a bounded", "insert"), ("Configure an observed", "recipe"),
    ("Connect two distinct", "connect"), ("Refuel up to eight", "refuel"),
    ("Build one reusable", "power"), ("Harvest a bounded", "harvest_coal"),
]


@pytest.mark.parametrize("prefix,expected", SKILLS)
def test_all_skill_branches_compile(catalog, observation, prefix, expected):
    client = ScriptedClient(skill=prefix)
    policy = TypedPolicy(client, catalog, seed=123)
    code, receipt = policy.act(observation, 1)
    ast.parse(code)
    assert check_program(code) == code
    assert receipt["skill"] == expected and len(code) <= 10000
    assert not any(word in code for word in ("import ", "rcon", "send_command", "__"))
    assert all(1 <= len(q["criteria"]) <= 255 for _, qs in client.requests for q in qs.values())


def test_adjacent_side_decision_sees_selected_entity(catalog, observation):
    client = ScriptedClient(skill="Place a structure directly")
    TypedPolicy(client, catalog, seed=123).act(observation, 1)
    selected = [(state, qs) for state, qs in client.requests if "side" in qs]
    assert selected and "chosen_entity" in selected[0][0]


def test_connect_target_sees_source_and_cannot_equal_it(catalog, observation):
    client = ScriptedClient(skill="Connect two distinct")
    TypedPolicy(client, catalog, seed=123).act(observation, 1)
    state, qs = next((s, q) for s, q in client.requests if "target" in q)
    source_name = state["connection_source"]["name"]
    assert all(not label.startswith(source_name + " at") for label in qs["target"]["criteria"].values())


def test_inventory_filters_unavailable_structures(catalog, observation):
    observation["inventory"] = [{"type": "coal", "quantity": 0}]
    client = ScriptedClient(skill="Locate the nearest")
    TypedPolicy(client, catalog, 1).act(observation, 1)
    labels = next(q["skill"]["criteria"].values() for _, q in client.requests if "skill" in q)
    assert not any(label.startswith(("Place", "Build", "Insert", "Refuel")) for label in labels)


def test_no_arbitrary_code_in_selection(catalog, observation):
    class Evil:
        def choose(self, state, questions):
            return {name: "__import__('os').system('bad')" for name in questions}
    with pytest.raises(ValueError, match="option set"):
        TypedPolicy(Evil(), catalog, 1).act(observation, 1)


def test_entity_parser_is_not_eval(catalog):
    obs = {"entities": ["__import__('os').system('echo unsafe')", "name='stone-furnace' position=Position(x=1.5 y=-2.5)"]}
    refs, report = entity_refs(obs, catalog)
    assert len(refs) == 1 and report["unparsed_entity_entries"] == 1
    assert refs[0].x == 1.5 and refs[0].y == -2.5


def test_entities_capped_and_omissions_reported(catalog):
    obs = {"entities": [f"name='wooden-chest' position=Position(x={i}, y=0)" for i in range(55)]}
    refs, info = entity_refs(obs, catalog)
    assert len(refs) == 40 and info["omitted_entity_references"] == 15


@pytest.mark.parametrize("code", ["import os", "eval('1')", "x.__class__", "while True: pass", "f = lambda: 1", "open('x')"])
def test_unapproved_program_rejected(code):
    with pytest.raises(ValueError):
        check_program(code)


@pytest.mark.parametrize("quantity", [-1, 1.5, "10", True])
def test_invalid_inventory_rejected(quantity):
    with pytest.raises(ValueError):
        inventory({"inventory": [{"type": "coal", "quantity": quantity}]})


def test_policy_seed_reproduces_criteria_order(catalog, observation):
    a, b = ScriptedClient(skill="Locate the nearest"), ScriptedClient(skill="Locate the nearest")
    code_a = TypedPolicy(a, catalog, 42).act(copy.deepcopy(observation), 1)
    code_b = TypedPolicy(b, catalog, 42).act(copy.deepcopy(observation), 1)
    assert code_a == code_b and a.requests == b.requests
