from __future__ import annotations
import argparse
import contextlib
import getpass
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from . import FLE_COMMIT, MODEL, TASKS
from . import cluster
from .client import JevClient
from .report import write_report
from .runtime import run_episode
from .util import Journal, atomic_json, digest, load_events, source_fingerprint


def validate_config(value: dict) -> dict:
    required = {"policy", "tasks", "steps", "attempts", "policy_seed", "episode_timeout_seconds"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("Config must contain exactly: " + ", ".join(sorted(required)))
    if value["policy"] not in {"jev", "random", "engine-smoke"}:
        raise ValueError("Unknown policy")
    tasks = value["tasks"]
    if not isinstance(tasks, list) or not tasks or any(t not in TASKS for t in tasks) or len(set(tasks)) != len(tasks):
        raise ValueError("Tasks must be a nonempty, unique list of pinned lab-play task IDs")
    for key, lo, hi in (("steps", 1, 64), ("attempts", 1, 8), ("policy_seed", 0, 2**31 - 1),
                        ("episode_timeout_seconds", 10, 86400)):
        if type(value[key]) is not int or not lo <= value[key] <= hi:
            raise ValueError(f"{key} must be an integer in {lo}..{hi}")
    return value.copy()


def credential(prompt: bool) -> str:
    value = getpass.getpass("TypeSafe API key (hidden; not saved): ") if prompt else os.getenv("TYPESAFE_API_KEY", "")
    if not value.strip():
        raise ValueError("Use --prompt-key or set TYPESAFE_API_KEY locally. Never put keys in command arguments.")
    return value.strip()


@contextlib.contextmanager
def world_lock():
    cluster.RUNTIME.mkdir(parents=True, exist_ok=True)
    path = cluster.RUNTIME / "run.lock"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise RuntimeError("A benchmark owns the world (or left a stale .runtime/run.lock). Inspect it before retrying.") from None
    try:
        with os.fdopen(fd, "w") as out:
            json.dump({"pid": os.getpid(), "started_unix": time.time()}, out)
        yield
    finally:
        path.unlink(missing_ok=True)


def kill_worker(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)


def worker(job: dict, root: Path, key: str) -> tuple[dict, int]:
    job_file = root / "jobs" / (job["id"] + ".json")
    atomic_json(job_file, job)
    output = root / "episodes" / job["id"]
    console = root / "console" / (job["id"] + ".log")
    console.parent.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.endswith("API_KEY")}
    if key:
        env["TYPESAFE_API_KEY"] = key
    env["PYTHONUNBUFFERED"] = "1"
    args = [sys.executable, "-m", "jev_fle", "_episode", "--job", str(job_file), "--output", str(output)]
    failure = None
    started = time.monotonic()
    with console.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(args, cwd=cluster.ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=(os.name == "posix"))
        try:
            returncode = process.wait(timeout=job["episode_timeout_seconds"])
            if returncode:
                failure = f"Worker exited with status {returncode}"
        except subprocess.TimeoutExpired:
            failure = "Episode wall deadline exceeded; native verifier was not modified"
            kill_worker(process)
        except KeyboardInterrupt:
            failure = "User interrupted the episode"
            kill_worker(process)
    # Defensive redaction of any reflected key from third-party diagnostic output.
    if key:
        text = console.read_text(encoding="utf-8", errors="replace")
        console.write_text(text.replace(key, "[REDACTED]"), encoding="utf-8")
    path = output / "summary.json"
    events = load_events(output / "events.jsonl")
    attempts = sum(e["event"] == "api_attempt" for e in events)
    if failure or not path.exists():
        summary = {"task": job["task"], "attempt": job["attempt"], "policy": job["policy"],
                   "status": "interrupted", "success": None, "steps": sum(e["event"] == "step" for e in events),
                   "max_steps": job["steps"], "error": failure or "Worker produced no summary",
                   "api_attempts": attempts, "wall_seconds": time.monotonic() - started}
        atomic_json(path, summary)
    else:
        summary = json.loads(path.read_text(encoding="utf-8"))
    return summary, attempts


def execute(config: dict, output: Path, key: str, max_api_calls: int) -> int:
    config = validate_config(config)
    if config["policy"] == "jev" and (not key or max_api_calls < 1):
        raise ValueError("A live Jev run requires a key and an explicit positive API-call cap")
    output = output.resolve()
    with world_lock():
        engine = cluster.managed_engine()  # Before any reset, require owned image/ports/project.
        fle = cluster.pinned_installation()
        output.mkdir(parents=True, exist_ok=False)
        jobs = []
        for task_index, task in enumerate(config["tasks"]):
            for attempt in range(1, config["attempts"] + 1):
                jobs.append({"id": f"{task}__{attempt:02d}", "task": task, "attempt": attempt,
                             "policy": config["policy"], "steps": config["steps"],
                             "policy_seed": config["policy_seed"] + task_index * 1009 + attempt,
                             "episode_timeout_seconds": config["episode_timeout_seconds"],
                             "port": engine["rcon_port"]})
        manifest = {"created_utc": datetime.now(timezone.utc).isoformat(), "config": config,
                    "config_sha256": digest(config), "jobs": jobs, "max_api_calls": max_api_calls,
                    "model": MODEL if config["policy"] == "jev" else None,
                    "fle": fle, "engine": engine, "source_fingerprint": source_fingerprint(),
                    "python": sys.version, "map_seed": None,
                    "protocol": "Native 0.3.0 verifier, custom Jev typed-action scaffold; not stock agent replication"}
        atomic_json(output / "manifest.json", manifest)
        environment = sorted(f"{d.metadata['Name']}=={d.version}" for d in importlib.metadata.distributions() if d.metadata.get("Name"))
        (output / "environment.freeze.txt").write_text("\n".join(environment) + "\n", encoding="utf-8")
        calls = 0
        failed = False
        try:
            for index, base_job in enumerate(jobs):
                if config["policy"] == "jev" and calls >= max_api_calls:
                    failed = True
                    atomic_json(output / "stop.json", {"reason": "global_api_budget_exhausted", "calls": calls})
                    break
                job = {**base_job, "max_api_calls": max(1, max_api_calls - calls)}
                print(f"Episode {index + 1}/{len(jobs)}: {job['task']} attempt {job['attempt']}", flush=True)
                summary, used = worker(job, output, key)
                calls += used
                write_report(output)
                print(f"  {summary['status']}; native_success={summary['success']}; API attempts={used}", flush=True)
                if summary["status"] != "complete":
                    failed = True
                    atomic_json(output / "stop.json", {"reason": "episode_interrupted", "episode": job["id"], "calls": calls})
                    # A killed worker can leave the game unpaused. Stop ONLY this disposable project.
                    try:
                        cluster.stop_cluster()
                    except Exception as exc:
                        atomic_json(output / "cleanup-warning.json", {"error_type": type(exc).__name__})
                    break
        except BaseException:
            failed = True
            atomic_json(output / "stop.json", {"reason": "parent_interrupted"})
            try:
                cluster.stop_cluster()
            except Exception:
                pass
            raise
        finally:
            result = write_report(output)
            print(f"Report: {output / 'report.md'}", flush=True)
            print(f"Completed {result['totals']['complete_episodes']}/{len(jobs)} episodes", flush=True)
        return 2 if failed else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Pinned FLE 0.3.0 / Jev typed-action benchmark setup")
    sub = parser.add_subparsers(dest="command", required=True)
    doc = sub.add_parser("doctor", help="Read-only dependency/source checks; never calls Jev")
    doc.add_argument("--engine", action="store_true")
    doc.add_argument("--output", type=Path)
    cl = sub.add_parser("cluster", help="Dedicated disposable benchmark world, loopback only")
    cl.add_argument("operation", choices=["start", "stop", "status"])
    cl.add_argument("--rcon-port", type=int, default=27100)
    cl.add_argument("--game-port", type=int, default=35197)
    api = sub.add_parser("api-smoke", help="Exactly one live Jev HTTP attempt; no game")
    api.add_argument("--allow-live", action="store_true")
    api.add_argument("--prompt-key", action="store_true")
    api.add_argument("--output", type=Path, default=Path("results/api-smoke"))
    eng = sub.add_parser("engine-smoke", help="One real FLE step, no model calls")
    eng.add_argument("--ack-reset", action="store_true", help="Acknowledge reset of the dedicated benchmark world")
    eng.add_argument("--output", type=Path, default=Path("results/engine-smoke"))
    run = sub.add_parser("run", help="Run native tasks with the custom Jev or explicit random scaffold")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--allow-live", action="store_true", help="Authorize model API calls within the explicit cap")
    run.add_argument("--ack-reset", action="store_true")
    run.add_argument("--prompt-key", action="store_true")
    run.add_argument("--max-api-calls", type=int, default=0, help="Total HTTP attempts including retries; not a dollar cap")
    rep = sub.add_parser("report", help="Regenerate coverage-aware JSON and Markdown reports")
    rep.add_argument("directory", type=Path)
    ep = sub.add_parser("_episode", help=argparse.SUPPRESS)
    ep.add_argument("--job", required=True, type=Path)
    ep.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            data = cluster.doctor(args.engine)
            if args.output:
                atomic_json(args.output, data)
            print(json.dumps(data, indent=2))
            return 0 if data.get("fle_imports") and (not args.engine or data["engine_verified"]) else 2
        if args.command == "cluster":
            if (cluster.RUNTIME / "run.lock").exists() and args.operation in {"start", "stop"}:
                raise RuntimeError("A run owns the world; do not change its cluster")
            if args.operation == "start":
                with world_lock():
                    metadata = cluster.start_cluster(args.rcon_port, args.game_port)
                print(json.dumps(metadata, indent=2))
                print("Started dedicated world. Use doctor --engine after Factorio finishes initialization.")
            elif args.operation == "stop":
                with world_lock():
                    cluster.stop_cluster()
            else:
                print(json.dumps(cluster.managed_engine(), indent=2))
            return 0
        if args.command == "api-smoke":
            if not args.allow_live:
                raise ValueError("api-smoke requires --allow-live")
            key = credential(args.prompt_key)
            args.output.mkdir(parents=True, exist_ok=False)
            log = Journal(args.output / "events.jsonl")
            try:
                client = JevClient(key, max_calls=1, retries=0, emit=log)
                answer = client.choose({"inventory": {"coal": 0}, "device": "unfueled boiler"}, {
                    "fuel": {"type": "choice", "instructions": "Which next action has its inventory precondition satisfied?",
                             "criteria": {"collect": "Obtain coal", "insert": "Insert coal already in inventory"}}})
                atomic_json(args.output / "result.json", {"model": MODEL, "answer": answer,
                            "api_attempts": client.calls, "input_tokens": client.input_tokens,
                            "output_tokens": client.output_tokens, "benchmark_score": None})
                print(json.dumps({"model": MODEL, "answer": answer, "api_attempts": client.calls}))
            finally:
                log.close()
            return 0
        if args.command == "engine-smoke":
            if not args.ack_reset:
                raise ValueError("engine-smoke requires --ack-reset for the dedicated benchmark world")
            return execute({"policy": "engine-smoke", "tasks": ["iron_ore_throughput"], "steps": 1,
                            "attempts": 1, "policy_seed": 0, "episode_timeout_seconds": 300}, args.output, "", 0)
        if args.command == "run":
            config = validate_config(json.loads(args.config.read_text(encoding="utf-8")))
            if not args.ack_reset:
                raise ValueError("run requires --ack-reset for the dedicated benchmark world")
            key = ""
            if config["policy"] == "jev":
                if not args.allow_live or args.max_api_calls < 1:
                    raise ValueError("Jev requires --allow-live and an explicit positive --max-api-calls")
                key = credential(args.prompt_key)
            return execute(config, args.output, key, args.max_api_calls)
        if args.command == "report":
            print(json.dumps(write_report(args.directory.resolve()), indent=2))
            return 0
        if args.command == "_episode":
            summary = run_episode(json.loads(args.job.read_text(encoding="utf-8")), args.output)
            return 0 if summary["status"] == "complete" else 2
    except (Exception, KeyboardInterrupt) as exc:
        # No traceback/locals that might contain bearer credentials.
        text = str(exc)
        secret = os.getenv("TYPESAFE_API_KEY", "")
        if secret:
            text = text.replace(secret, "[REDACTED]")
        print(f"ERROR: {type(exc).__name__}: {text}", file=sys.stderr)
        return 2
    return 0
