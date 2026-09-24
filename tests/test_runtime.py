import copy
from dataclasses import dataclass
import json
from pathlib import Path
import pytest
from jev_fle.runtime import run_episode, validate_step
from jev_fle.util import jsonable, load_events


class State:
    def to_raw(self):
        return '{"fixture": "not a real Factorio state"}'


@dataclass
class FakeAction:
    code: str
    agent_idx: int = 0


class FakeEnv:
    def __init__(self, observation, *, succeed_at=None, error_at=None, truncate=False):
        self.observation = copy.deepcopy(observation)
        self.succeed_at, self.error_at, self.truncate = succeed_at, error_at, truncate
        self.task = type("Task", (), {"starting_game_state": State()})()
        self.instance = self
        self.steps = self.pauses = 0
        self.reset_kwargs = None
        self.closed = False

    def pause(self):
        self.pauses += 1

    def reset(self, **kwargs):
        self.reset_kwargs = kwargs
        return self.observation

    def step(self, action):
        assert isinstance(action, FakeAction), "Expected Action dataclass, not a dictionary"
        self.steps += 1
        if self.steps == self.error_at:
            raise RuntimeError("synthetic infrastructure failure")
        success = self.steps == self.succeed_at
        self.observation["task_verification"]["success"] = int(success)
        self.observation["game_info"]["tick"] += 3600
        return self.observation, 999.0, success, self.truncate, {"error_occurred": False}

    def close(self):
        self.closed = True


def job(steps=64):
    return {"task": "iron_ore_throughput", "attempt": 1, "policy": "engine-smoke", "policy_seed": 0,
            "steps": steps, "port": 27100, "max_api_calls": 1}


def execute_fixture(tmp_path, catalog, observation, **kwargs):
    env = FakeEnv(observation, **kwargs)
    result = run_episode(job(), tmp_path / "episode", env_factory=lambda t, p: env,
                         catalog=catalog, action_factory=FakeAction)
    return env, result


def test_step_limit_and_native_success_not_reward(tmp_path, catalog, observation):
    env, result = execute_fixture(tmp_path, catalog, observation)
    assert result["status"] == "complete" and result["success"] is False and env.steps == 64
    assert "seed" not in env.reset_kwargs and "game_state" in env.reset_kwargs["options"]
    assert env.closed and env.pauses >= 2
    assert (tmp_path / "episode" / "initial-state.json.gz").exists()


def test_native_success_stops_early(tmp_path, catalog, observation):
    env, result = execute_fixture(tmp_path, catalog, observation, succeed_at=3)
    assert result["success"] is True and result["steps"] == 3 and env.steps == 3


def test_infrastructure_failure_is_not_a_benchmark_failure(tmp_path, catalog, observation):
    _, result = execute_fixture(tmp_path, catalog, observation, error_at=2)
    assert result["status"] == "interrupted" and result["success"] is None
    assert result["steps"] == 1


def test_premature_truncation_is_interruption(tmp_path, catalog, observation):
    _, result = execute_fixture(tmp_path, catalog, observation, truncate=True)
    assert result["status"] == "interrupted" and result["success"] is None


def test_gymnasium_reset_shape_rejected(tmp_path, catalog, observation):
    env = FakeEnv(observation)
    env.reset = lambda **kwargs: (observation, {})
    result = run_episode(job(), tmp_path / "episode", env_factory=lambda t,p: env,
                         catalog=catalog, action_factory=FakeAction)
    assert result["status"] == "interrupted" and env.steps == 0


def test_native_verification_disagreement_fails_closed():
    with pytest.raises(RuntimeError, match="disagree"):
        validate_step({"task_verification": {"success": 0}}, True)


def test_numpy_scalars_optional():
    np = pytest.importorskip("numpy")
    assert jsonable({"i": np.int32(5), "b": np.bool_(True)}) == {"i": 5, "b": True}


def test_corrupt_earlier_journal_not_ignored(tmp_path):
    path = tmp_path / "e.jsonl"
    path.write_text('{"event":"a"}\n{broken\n{"event":"b"}\n')
    with pytest.raises(ValueError, match="Corrupt"):
        load_events(path)
    path.write_text('{"event":"a"}\n{broken')
    assert load_events(path) == [{"event": "a"}]


def test_real_adapter_loop_with_synthetic_http_and_engine(tmp_path, catalog, observation):
    """Contract integration only: neither endpoint nor engine is real in this test."""
    from jev_fle import MODEL
    from jev_fle.client import JevClient
    env = FakeEnv(observation, succeed_at=2)
    def transport(payload):
        data = json.loads(payload)
        answers = {}
        for name, question in data["questions"].items():
            options = question["criteria"]
            key = (next(k for k, v in options.items() if v.startswith("Locate the nearest"))
                   if name == "skill" else next(iter(options)))
            answers[name] = {"type": "choice", "choice": key, "confidence": 1.0,
                             "probabilities": {k: float(k == key) for k in options}}
        return {"model": MODEL, "answers": answers, "usage": {"input_tokens": 100, "output_tokens": 5}}
    settings = {**job(), "policy": "jev", "max_api_calls": 20}
    result = run_episode(settings, tmp_path / "episode", env_factory=lambda t,p: env,
                         catalog=catalog, action_factory=FakeAction,
                         client_factory=lambda log: JevClient("fixture-key", max_calls=20, transport=transport, emit=log))
    assert result["status"] == "complete" and result["success"] is True
    assert result["api_attempts"] == 4 and result["input_tokens"] == 400
    events = load_events(tmp_path / "episode" / "events.jsonl")
    assert sum(e["event"] == "action" for e in events) == 2
    assert "fixture-key" not in json.dumps(events)


def test_unknown_or_non_owned_port_not_reset(monkeypatch):
    from jev_fle import runtime
    monkeypatch.setattr(runtime, "pinned_installation", lambda: {})
    monkeypatch.setattr(runtime, "managed_engine", lambda: {"rcon_port": 27100})
    with pytest.raises(RuntimeError, match="dedicated world"):
        runtime.make_environment("iron_ore_throughput", 27000)
