from __future__ import annotations
import hashlib
import json
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Any


def jsonable(value: Any) -> Any:
    """Convert native/Gym scalars without evaluating strings or deserializing pickles."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite number in benchmark data")
        return value
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if type(value).__module__.startswith("numpy") and hasattr(value, "item"):
        return jsonable(value.item())
    raise TypeError(f"Unsupported telemetry type: {type(value).__name__}")


def canonical(value: Any) -> str:
    return json.dumps(jsonable(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".partial-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(jsonable(value), out, indent=2, ensure_ascii=False, allow_nan=False)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Journal:
    """Append-only receipts; record attempts before sending a potentially billable call."""
    def __init__(self, path: Path):
        self.path = path
        self.handle = path.open("a", encoding="utf-8")

    def __call__(self, kind: str, **values: Any) -> None:
        self.handle.write(canonical({"event": kind, "time_unix": time.time(), **values}) + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())

    def close(self) -> None:
        self.handle.close()


def load_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    result = []
    for i, line in enumerate(lines):
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            if i != len(lines) - 1:
                raise ValueError(f"Corrupt journal before final line: {path}")
            # A killed worker may leave one incomplete final write.
    return result


def source_fingerprint() -> str:
    root = Path(__file__).parent
    return digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(root.glob("*.py"))})
