"""Manage only the dedicated jev-fle030 Compose project; never the user's game."""
from __future__ import annotations
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path
from . import FLE_COMMIT, FACTORIO_IMAGE, UPSTREAM_BLOBS
from .util import atomic_json

PROJECT = "jev-fle030"
ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
COMPOSE = RUNTIME / "compose.json"
META = RUNTIME / "cluster.json"


def pinned_installation() -> dict:
    """Fail closed on source drift, not just a distribution version string."""
    distribution = importlib.metadata.distribution("factorio-learning-environment")
    version = distribution.version
    if version != "0.3.0":
        raise RuntimeError(f"Expected FLE 0.3.0, found {version}")
    provenance = json.loads(distribution.read_text("direct_url.json") or "{}")
    if provenance.get("vcs_info", {}).get("commit_id") != FLE_COMMIT:
        raise RuntimeError("FLE must be installed from the pinned Git commit using requirements-fle.txt")
    spec = importlib.util.find_spec("fle")
    if spec is None or not spec.origin:
        raise RuntimeError("FLE package not found")
    package = Path(spec.origin).parent
    checked = {}
    for relative, expected in UPSTREAM_BLOBS.items():
        data = (package / relative).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Pinned FLE source mismatch: {relative}")
        checked[relative] = actual
    return {"distribution_version": version, "verified_install_commit": FLE_COMMIT,
            "verified_git_blobs": checked, "package_directory": str(package)}


def command(args: list[str], *, capture: bool = False, timeout: int = 60) -> str:
    # Docker never receives the TypeSafe bearer key, even as an inherited process variable.
    env = {k: v for k, v in os.environ.items() if not k.endswith("API_KEY")}
    result = subprocess.run(args, check=True, text=True, capture_output=capture,
                            env=env, timeout=timeout)
    return result.stdout.strip() if capture else ""


def compose_args(*args: str) -> list[str]:
    return ["docker", "compose", "-p", PROJECT, "-f", str(COMPOSE), *args]


def prepare_cluster(rcon_port: int = 27100, game_port: int = 35197) -> dict:
    if not (1024 <= rcon_port <= 65535 and 1024 <= game_port <= 65535):
        raise ValueError("Ports must be in 1024..65535")
    if rcon_port == 27000 or game_port == 34197:
        raise ValueError("Use dedicated ports, not FLE's standard cluster ports")
    verified = pinned_installation()
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("This validated setup profile targets x86-64 Linux / Docker Desktop / WSL2")
    if COMPOSE.exists() or META.exists():
        if not (COMPOSE.exists() and META.exists()):
            raise RuntimeError("Partial cluster configuration exists; inspect .runtime before retrying")
        existing = json.loads(META.read_text())
        if (existing.get("project"), existing.get("rcon_port"), existing.get("game_port")) != (PROJECT, rcon_port, game_port):
            raise RuntimeError("Refusing to replace an existing cluster configuration")
        return existing
    from fle.cluster.run_envs import ComposeGenerator
    RUNTIME.mkdir(exist_ok=True)
    generator = ComposeGenerator(scenario="default_lab_scenario", attach_mod=False,
                                 state_dir=RUNTIME / "fle-state", work_dir=RUNTIME)
    data = generator.compose_dict(1)
    service = data["services"]["factorio_0"]
    if service["image"] != FACTORIO_IMAGE:
        raise RuntimeError("Unexpected upstream Factorio image")
    # Upstream enables a whitelist but does not ship its file. This dedicated
    # loopback-only server must allow the local GUI spectator to connect.
    service["command"] = service["command"].replace(
        " --server-whitelist /opt/factorio/config/server-whitelist.json --use-server-whitelist", "")
    service["ports"] = [f"127.0.0.1:{game_port}:34197/udp", f"127.0.0.1:{rcon_port}:27015/tcp"]
    service["restart"] = "no"
    atomic_json(COMPOSE, data)
    metadata = {"project": PROJECT, "rcon_port": rcon_port, "game_port": game_port,
                "bind_address": "127.0.0.1", "scenario": "default_lab_scenario",
                "image_tag": FACTORIO_IMAGE, "image_digest": None,
                "source": verified, "note": "Dedicated disposable benchmark world; not a gameplay save."}
    atomic_json(META, metadata)
    return metadata


def start_cluster(rcon_port: int = 27100, game_port: int = 35197) -> dict:
    command(["docker", "info"], capture=True)
    command(["docker", "compose", "version"], capture=True)
    metadata = prepare_cluster(rcon_port, game_port)
    if not metadata.get("image_digest"):
        command(compose_args("pull"), timeout=1200)
        info = json.loads(command(["docker", "image", "inspect", FACTORIO_IMAGE], capture=True))[0]
        digests = info.get("RepoDigests", [])
        if not digests:
            raise RuntimeError("Docker image has no registry digest; refusing an unpinned run")
        preferred = [d for d in digests if d.startswith("factoriotools/factorio@sha256:")]
        if not preferred:
            raise RuntimeError("Unexpected image repository digest")
        metadata["image_digest"] = preferred[0]
        metadata["image_id"] = info["Id"]
        config = json.loads(COMPOSE.read_text())
        config["services"]["factorio_0"]["image"] = preferred[0]
        atomic_json(COMPOSE, config)
        atomic_json(META, metadata)
    command(compose_args("up", "-d"), timeout=300)
    return metadata


def managed_engine() -> dict:
    if not META.exists() or not COMPOSE.exists():
        raise RuntimeError("Run cluster start first; no arbitrary RCON endpoint is accepted")
    metadata = json.loads(META.read_text())
    if metadata.get("project") != PROJECT or not metadata.get("image_digest"):
        raise RuntimeError("Unverified managed cluster metadata")
    container_id = command(compose_args("ps", "-q", "factorio_0"), capture=True)
    if not container_id or "\n" in container_id:
        raise RuntimeError("Expected exactly one dedicated Factorio container")
    info = json.loads(command(["docker", "inspect", container_id], capture=True))[0]
    labels = info.get("Config", {}).get("Labels", {})
    if labels.get("com.docker.compose.project") != PROJECT or not info["State"]["Running"]:
        raise RuntimeError("Dedicated benchmark container is not running")
    if info.get("Image") != metadata.get("image_id"):
        raise RuntimeError("Running image differs from the recorded Docker image ID")
    bindings = info.get("HostConfig", {}).get("PortBindings", {})
    for port, expected in (("27015/tcp", metadata["rcon_port"]), ("34197/udp", metadata["game_port"])):
        entries = bindings.get(port, [])
        if len(entries) != 1 or entries[0].get("HostIp") != "127.0.0.1" or entries[0].get("HostPort") != str(expected):
            raise RuntimeError("Benchmark port binding is not the expected loopback-only binding")
    version = command(compose_args("exec", "-T", "factorio_0", "/opt/factorio/bin/x64/factorio", "--version"), capture=True)
    if "Version: 1.1.110" not in version:
        raise RuntimeError("Expected Factorio server version 1.1.110")
    with socket.create_connection(("127.0.0.1", metadata["rcon_port"]), timeout=5):
        pass
    return {**metadata, "container_id": container_id, "server_version_output": version}


def stop_cluster() -> None:
    if not COMPOSE.exists() or not META.exists():
        raise RuntimeError("No managed benchmark cluster configuration found")
    if json.loads(META.read_text()).get("project") != PROJECT:
        raise RuntimeError("Unexpected Compose project")
    command(compose_args("down"), timeout=120)


def doctor(check_engine: bool = False) -> dict:
    result = {"python": platform.python_version(), "platform": platform.platform(),
              "machine": platform.machine(), "docker_cli": bool(shutil.which("docker")),
              "typesafe_api_key_present": bool(os.environ.get("TYPESAFE_API_KEY")),
              "fle_pinned_source": False, "engine_verified": False, "errors": []}
    try:
        result["fle_details"] = pinned_installation()
        result["fle_pinned_source"] = True
        # Exercise the actual integration imports, not merely pip metadata.
        from fle.env.gym_env.registry import GymEnvironmentSpec, make_factorio_env
        from fle.env.gym_env.action import Action
        from fle.eval.tasks.task_definitions.lab_play.throughput_tasks import THROUGHPUT_TASKS
        from . import TASKS
        if set(THROUGHPUT_TASKS) != set(TASKS):
            raise RuntimeError("Upstream task registry differs from the 24-task manifest")
        result["fle_imports"] = True
        result["task_count"] = len(THROUGHPUT_TASKS)
    except Exception as exc:
        result["fle_imports"] = False
        result["errors"].append(f"FLE: {type(exc).__name__}: {exc}")
    if check_engine:
        try:
            result["engine"] = managed_engine()
            result["engine_verified"] = True
        except Exception as exc:
            result["errors"].append(f"Engine: {type(exc).__name__}: {exc}")
    result["ready_for_live_run"] = bool(result.get("fle_imports") and result["engine_verified"]
                                         and result["typesafe_api_key_present"])
    return result
