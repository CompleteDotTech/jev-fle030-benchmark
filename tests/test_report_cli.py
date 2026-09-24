import copy
import json
from pathlib import Path
import pytest
from jev_fle import TASKS, FLE_COMMIT
from jev_fle.cli import main, validate_config
from jev_fle.report import compile_report
from jev_fle.util import atomic_json


def make_run(root, *, steps=64, completed=8, interrupted=0, all_tasks=False):
    tasks = list(TASKS) if all_tasks else [TASKS[0]]
    config = {"policy": "jev", "tasks": tasks, "steps": steps, "attempts": 8,
              "policy_seed": 1, "episode_timeout_seconds": 60}
    jobs = []
    for task in tasks:
        for attempt in range(1, 9):
            entry = {"id": f"{task}__{attempt:02d}", "task": task, "attempt": attempt}
            jobs.append(entry)
            if attempt <= completed + interrupted:
                summary = {"task": task, "attempt": attempt, "policy": "jev", "max_steps": steps,
                           "steps": steps, "status": "complete" if attempt <= completed else "interrupted",
                           "success": attempt == 1 if attempt <= completed else None}
                atomic_json(root / "episodes" / entry["id"] / "summary.json", summary)
    atomic_json(root / "manifest.json", {"config": config, "jobs": jobs})


def test_complete_eight_task_is_eligible_but_partial_suite_has_no_aggregate(tmp_path):
    make_run(tmp_path)
    result = compile_report(tmp_path)
    assert result["tasks"][0]["empirical_pass_at_8"] is True
    assert result["labplay_empirical_pass_at_8"] is None


def test_interrupted_trial_not_denominator(tmp_path):
    make_run(tmp_path, completed=7, interrupted=1)
    row = compile_report(tmp_path)["tasks"][0]
    assert row["complete"] == 7 and row["interrupted"] == 1
    assert row["empirical_pass_at_8"] is None


def test_smoke_never_pass_at_eight(tmp_path):
    make_run(tmp_path, steps=4)
    result = compile_report(tmp_path)
    assert result["tasks"][0]["empirical_pass_at_8"] is None


def test_full_synthetic_coverage_math(tmp_path):
    make_run(tmp_path, all_tasks=True)
    result = compile_report(tmp_path)
    assert result["labplay_empirical_pass_at_8"] == 1.0
    assert result["totals"]["planned_episodes"] == 192


def test_not_started_remains_explicit(tmp_path):
    make_run(tmp_path, completed=2, interrupted=1)
    row = compile_report(tmp_path)["tasks"][0]
    assert row["not_started"] == 5


@pytest.mark.parametrize("field,value", [("steps", 65), ("attempts", 0), ("attempts", True),
                                        ("policy", "chatgpt"), ("tasks", ["sulfuric_acid_throughput"]),
                                        ("tasks", [TASKS[0], TASKS[0]])])
def test_config_rejects_invalid_or_non_native_tasks(field, value):
    config = {"policy": "jev", "tasks": [TASKS[0]], "steps": 64, "attempts": 8,
              "policy_seed": 1, "episode_timeout_seconds": 60}
    config[field] = value
    with pytest.raises(ValueError):
        validate_config(config)


def test_all_bundled_configs_valid():
    root = Path(__file__).resolve().parents[1]
    for path in (root / "configs").glob("*.json"):
        validate_config(json.loads(path.read_text()))
    assert FLE_COMMIT in (root / "requirements-fle.txt").read_text()


def test_no_live_call_without_authorization(tmp_path, capsys):
    assert main(["api-smoke", "--output", str(tmp_path / "no")]) == 2
    assert not (tmp_path / "no").exists()
    assert "--allow-live" in capsys.readouterr().err


def test_engine_reset_requires_acknowledgment(capsys):
    assert main(["engine-smoke"]) == 2
    assert "--ack-reset" in capsys.readouterr().err
