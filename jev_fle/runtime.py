from __future__ import annotations
import gzip
import hashlib
import json
import os
import random
import time
from pathlib import Path
from . import TASKS
from .client import JevClient, RandomClient
from .cluster import pinned_installation, managed_engine
from .policy import Catalog, TypedPolicy
from .util import Journal, atomic_json, jsonable


def observation_record(observation: dict) -> dict:
    data = jsonable(observation)
    # Never unpickle, evaluate, or send serialized helper functions to Jev.
    functions = data.pop("serialized_functions", [])
    data["serialized_function_count"] = len(functions)
    data.pop("map_image", None)  # Jev is text-only; this profile disables vision.
    return data


def make_environment(task: str, port: int):
    if task not in TASKS:
        raise ValueError("Unknown lab-play task")
    pinned_installation()
    owned = managed_engine()
    if port != owned["rcon_port"]:
        raise RuntimeError("Episode port differs from the verified dedicated world")
    # Always use the already-verified dedicated LOCAL server, regardless of inherited env.
    os.environ["FACTORIO_SERVER_ADDRESS"] = "127.0.0.1"
    os.environ["FACTORIO_SERVER_PORT"] = str(port)
    from fle.env.gym_env.registry import GymEnvironmentSpec, make_factorio_env
    spec = GymEnvironmentSpec(task_key=task, task_config_path=task,
                              description="Pinned FLE 0.3.0 lab-play", num_agents=1, enable_vision=False)
    env = make_factorio_env(spec, run_idx=0)
    if env.task.trajectory_length != 64 or env.task.holdout_wait_period != 60:
        env.close()
        raise RuntimeError("Unexpected upstream step or holdout configuration")
    return env


def validate_step(observation: dict, terminated: bool) -> bool:
    success = observation.get("task_verification", {}).get("success")
    if success not in (0, 1, False, True):
        raise RuntimeError("Missing or invalid native FLE task verification")
    if bool(success) != bool(terminated):
        raise RuntimeError("Native termination and verification disagree")
    return bool(success)


def run_episode(job: dict, output: Path, *, env_factory=None, catalog=None,
                action_factory=None, client_factory=None) -> dict:
    """An episode is run in a killable subprocess by the CLI. Dependency injection is test-only."""
    output.mkdir(parents=True, exist_ok=False)
    log = Journal(output / "events.jsonl")
    env = None
    start = time.monotonic()
    summary = {"task": job["task"], "attempt": job["attempt"], "policy": job["policy"],
               "policy_seed": job["policy_seed"], "map_seed": None,
               "map_seed_note": "FLE 0.3.0 reset(seed=...) ignores seed; no seed argument is passed.",
               "status": "interrupted", "success": None, "steps": 0,
               "step_errors": 0, "max_steps": job["steps"]}
    client = None
    try:
        if job["task"] not in TASKS or not 1 <= job["steps"] <= 64:
            raise ValueError("Invalid task or step budget")
        if env_factory is None:
            env_factory = make_environment
        if action_factory is None:
            from fle.env.gym_env.action import Action
            action_factory = Action
        if catalog is None:
            catalog = Catalog.from_fle()
        env = env_factory(job["task"], job["port"])
        initial_state = env.task.starting_game_state
        raw = initial_state.to_raw()
        raw_bytes = raw.encode("utf-8")
        with gzip.open(output / "initial-state.json.gz", "wb") as out:
            out.write(raw_bytes)
        summary["initial_state_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
        observation = env.reset(options={"game_state": initial_state})
        if not isinstance(observation, dict):
            raise RuntimeError("Pinned FLE reset must return a dictionary, not a Gymnasium tuple")
        env.instance.pause()
        observation = observation_record(observation)
        log("episode_start", job=job, initial_observation=observation,
            initial_state_sha256=summary["initial_state_sha256"])
        if client_factory is not None:
            client = client_factory(log)
        elif job["policy"] == "jev":
            client = JevClient(os.environ.get("TYPESAFE_API_KEY", ""), max_calls=job["max_api_calls"], emit=log)
        elif job["policy"] == "random":
            client = RandomClient(random.Random(job["policy_seed"]))
        elif job["policy"] != "engine-smoke":
            raise ValueError("Unknown policy; no implicit fallback")
        policy = TypedPolicy(client, catalog, job["policy_seed"], emit=log) if client else None
        for step in range(1, job["steps"] + 1):
            if policy:
                code, decision = policy.act(observation, step)
            else:
                code, decision = "print(inspect_inventory())\n", {"kind": "engine-plumbing-only"}
            log("action", step=step, code=code, decision=decision)
            tick_start = observation.get("game_info", {}).get("tick", 0)
            action_start = time.monotonic()
            observation, reward, terminated, truncated, info = env.step(action_factory(code=code, agent_idx=0))
            observation = observation_record(observation)
            native_success = validate_step(observation, terminated)
            summary["steps"] = step
            summary["step_errors"] += int(bool(info.get("error_occurred", False)))
            log("step", step=step, observation=observation, reward=reward,
                terminated=bool(terminated), truncated=bool(truncated),
                native_success=native_success, error_occurred=bool(info.get("error_occurred", False)),
                ticks_before=tick_start, ticks_after=observation.get("game_info", {}).get("tick"),
                wall_seconds=time.monotonic() - action_start)
            if truncated and not terminated:
                raise RuntimeError("Native environment truncated the episode before completion")
            if terminated:
                break
        summary.update(status="complete", success=native_success)
    except BaseException as exc:
        secret = os.environ.get("TYPESAFE_API_KEY", "")
        text = str(exc).replace(secret, "[REDACTED]") if secret else str(exc)
        summary.update(error_type=type(exc).__name__, error=text[:1200])
        log("episode_error", error_type=summary["error_type"], error=summary["error"])
    finally:
        if env is not None:
            try:
                env.instance.pause()
                env.close()
            except Exception as exc:
                log("cleanup_error", error_type=type(exc).__name__)
        summary["wall_seconds"] = time.monotonic() - start
        summary["api_attempts"] = getattr(client, "calls", 0)
        summary["input_tokens"] = getattr(client, "input_tokens", 0)
        summary["output_tokens"] = getattr(client, "output_tokens", 0)
        atomic_json(output / "summary.json", summary)
        log("episode_end", summary=summary)
        log.close()
    return summary
