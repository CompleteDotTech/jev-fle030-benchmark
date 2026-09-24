"""Synthetic fixtures only; none of these are Factorio benchmark measurements."""
from copy import deepcopy
import pytest
from jev_fle.policy import Catalog


@pytest.fixture
def catalog():
    names = {
        "coal": "Coal", "iron-ore": "IronOre", "copper-ore": "CopperOre", "stone": "Stone",
        "iron-plate": "IronPlate", "iron-gear-wheel": "IronGearWheel",
        "stone-furnace": "StoneFurnace", "burner-mining-drill": "BurnerMiningDrill",
        "electric-mining-drill": "ElectricMiningDrill", "assembling-machine-2": "AssemblingMachine2",
        "inserter": "Inserter", "transport-belt": "TransportBelt", "wooden-chest": "WoodenChest",
        "offshore-pump": "OffshorePump", "boiler": "Boiler", "steam-engine": "SteamEngine",
        "pipe": "Pipe", "medium-electric-pole": "MediumElectricPole", "oil-refinery": "OilRefinery",
        "chemical-plant": "ChemicalPlant", "pumpjack": "PumpJack",
    }
    recipes = {n: f"Prototype.{p}" for n, p in names.items() if n not in {"coal", "iron-ore", "copper-ore", "stone"}}
    recipes["basic-oil-processing"] = "RecipeName.BasicOilProcessing"
    return Catalog(names, recipes)


@pytest.fixture
def observation(catalog):
    return {
        "inventory": [{"type": name, "quantity": 500} for name in catalog.prototypes],
        "entities": [
            "Furnace(name='stone-furnace', position=Position(x=1.5, y=-2.5), energy=0)",
            "AdvancedAssemblingMachine(name='assembling-machine-2', position=Position(x=7.5, y=3.5), recipe=None)",
            "Chest(name='wooden-chest', position=Position(x=12, y=4), inventory={'iron-plate': 20})",
        ],
        "raw_text": "SYNTHETIC TEST FIXTURE, NOT A REAL BENCHMARK RUN",
        "task_info": {"task_key": "iron_ore_throughput", "goal_description": "Create an automatic iron-ore factory",
                      "trajectory_length": 64},
        "game_info": {"tick": 0, "time": 0.0, "speed": 10},
        "task_verification": {"success": 0, "meta": []},
        "serialized_functions": [], "map_image": "",
    }


class ScriptedClient:
    def __init__(self, **hints):
        self.hints = hints
        self.requests = []
        self.calls = self.input_tokens = self.output_tokens = 0

    def choose(self, state, questions):
        self.requests.append((deepcopy(state), deepcopy(questions)))
        result = {}
        for name, q in questions.items():
            criteria = q["criteria"]
            prefix = self.hints.get(name)
            choices = [key for key, label in criteria.items() if prefix is None or label.startswith(prefix)]
            if not choices:
                raise AssertionError(f"Hint {name}={prefix!r} not offered: {criteria}")
            result[name] = choices[0]
        return result
