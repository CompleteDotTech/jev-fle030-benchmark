#!/usr/bin/env python3
"""Create a LOCAL virtualenv and install the pinned source. No Docker or Jev calls.

Network access is needed for Python/dependencies/GitHub. Existing .venv is never overwritten.
On an offline host, use a pre-provisioned wheelhouse and the documented requirements.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def run(args, **kwargs):
    print("+ " + " ".join(map(str, args)), flush=True)
    # Dependency tools never need the user's model credentials.
    env = {k: v for k, v in os.environ.items() if not k.endswith("API_KEY")}
    return subprocess.run(list(map(str, args)), cwd=ROOT, env=env, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-venv", action="store_true", help="Explicitly reuse .venv after inspecting it")
    args = parser.parse_args()
    target = ROOT / ".venv"
    uv = shutil.which("uv")
    if target.exists() and not args.reuse_venv:
        raise RuntimeError(".venv exists; inspect it, then use --reuse-venv to continue")
    if not target.exists():
        if uv:
            run([uv, "venv", "--python", "3.11", target])
        elif sys.version_info[:2] in {(3, 11), (3, 12)}:
            venv.EnvBuilder(with_pip=True).create(target)
        else:
            raise RuntimeError("Install Python 3.11/3.12 or uv, then rerun. No system Python is modified.")
    python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        raise RuntimeError("Existing .venv has no Python executable for this operating system")
    installer = [uv, "pip", "install", "--python", python] if uv else [python, "-m", "pip", "install"]
    run([*installer, "-r", ROOT / "requirements-fle.txt", "-e", ".[test]"])
    freeze_cmd = [uv, "pip", "freeze", "--python", python] if uv else [python, "-m", "pip", "freeze", "--all"]
    freeze = run(freeze_cmd, capture_output=True, text=True).stdout
    (ROOT / "environment.freeze.txt").write_text(freeze, encoding="utf-8")
    run([python, "-m", "pytest", "-q"])
    # Import verification is part of installation, so dependency incompatibility is not hidden.
    run([python, "-m", "jev_fle", "doctor", "--output", ROOT / "installation-check.json"])
    print("Installed locally and checked imports. Docker and live Jev validation are separate steps in README.md.")


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        print(f"SETUP STOPPED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
