"""CompleteTech Jev adapter for the pinned FLE 0.3.0 lab-play benchmark."""
__version__ = "0.1.0"
FLE_COMMIT = "714482a6fc3ed3da6b6288c35fb697c458415e31"
MODEL = "jev-1.13.0"
FACTORIO_IMAGE = "factoriotools/factorio:1.1.110"
TASK_NAMES = (
    "advanced_circuit", "automation_science_pack", "battery", "chemical_science_pack",
    "crude_oil", "electronic_circuit", "engine_unit", "inserter", "iron_gear_wheel",
    "iron_ore", "iron_plate", "logistics_science_pack", "low_density_structure",
    "military_science_pack", "petroleum_gas", "piercing_round", "plastic_bar",
    "processing_unit", "production_science_pack", "steel_plate", "stone_wall",
    "sufuric_acid", "sulfur", "utility_science_pack",
)
TASKS = tuple(name + "_throughput" for name in TASK_NAMES)
# These are Git blob hashes, not SHA256 digests. Verified against upstream v0.3.0.
UPSTREAM_BLOBS = {
    "env/gym_env/action.py": "b151f64eb224bae7e3cd665f8a84b43bbf6047a2",
    "env/gym_env/environment.py": "001914bde49582a897525eac681af9905e69ff67",
    "env/gym_env/registry.py": "bba5e53cd038f1767504dda60aab2aab9f7edb2e",
    "env/gym_env/observation.py": "c35dbf68c73c02159bdc2ab47f7642cf96115750",
    "env/game_types.py": "45a1dfbe4d3a9f90180a4bd499319fb5242a4f96",
    "eval/tasks/throughput_task.py": "d538a298e88404623741a04f63e1c60b17c6f37d",
    "eval/tasks/task_definitions/lab_play/throughput_tasks.py": "b3b7a5a9b4fffe59152b34e262de35fb7c576da6",
    "cluster/run_envs.py": "bfb902a1189d437c67e43768317639dfe95a6cdd",
}
