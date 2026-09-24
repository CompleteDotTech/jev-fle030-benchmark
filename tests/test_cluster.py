import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from jev_fle import cluster, FLE_COMMIT
from jev_fle.cli import world_lock
from jev_fle.util import atomic_json


def fixture_install(tmp_path, monkeypatch, commit=FLE_COMMIT, content=b"fixture source\n"):
    package = tmp_path / "fle"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "example.py").write_bytes(content)
    sha = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
    monkeypatch.setattr(cluster, "UPSTREAM_BLOBS", {"example.py": sha})
    dist = SimpleNamespace(version="0.3.0", read_text=lambda f: json.dumps({"vcs_info": {"commit_id": commit}}))
    monkeypatch.setattr(cluster.importlib.metadata, "distribution", lambda name: dist)
    monkeypatch.setattr(cluster.importlib.util, "find_spec", lambda name: SimpleNamespace(origin=str(package / "__init__.py")))
    return package


def test_exact_git_install_and_source_blobs_checked(tmp_path, monkeypatch):
    fixture_install(tmp_path, monkeypatch)
    assert cluster.pinned_installation()["verified_install_commit"] == FLE_COMMIT


def test_wrong_install_commit_rejected(tmp_path, monkeypatch):
    fixture_install(tmp_path, monkeypatch, commit="0" * 40)
    with pytest.raises(RuntimeError, match="pinned Git commit"):
        cluster.pinned_installation()


def test_modified_critical_source_rejected(tmp_path, monkeypatch):
    package = fixture_install(tmp_path, monkeypatch)
    (package / "example.py").write_text("changed")
    with pytest.raises(RuntimeError, match="source mismatch"):
        cluster.pinned_installation()


@pytest.mark.parametrize("rcon,game", [(27000,35197),(27100,34197),(0,35197),(27100,70000)])
def test_standard_or_invalid_ports_rejected(rcon, game):
    with pytest.raises(ValueError):
        cluster.prepare_cluster(rcon, game)


def test_compose_always_uses_dedicated_project_and_file():
    args = cluster.compose_args("down")
    assert args[:4] == ["docker", "compose", "-p", "jev-fle030"]
    assert "-f" in args and args[-1] == "down"


def test_engine_without_managed_metadata_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(cluster, "META", tmp_path / "missing.json")
    monkeypatch.setattr(cluster, "command", lambda *a, **kw: pytest.fail("Must not contact arbitrary engine"))
    with pytest.raises(RuntimeError, match="no arbitrary RCON"):
        cluster.managed_engine()


def test_exclusive_world_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(cluster, "RUNTIME", tmp_path)
    with world_lock():
        assert (tmp_path / "run.lock").exists()
        with pytest.raises(RuntimeError, match="owns the world"):
            with world_lock():
                pass
    assert not (tmp_path / "run.lock").exists()


def test_docker_process_does_not_inherit_api_keys(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-key")
    monkeypatch.setenv("OTHER_API_KEY", "other-fake-key")
    def run(args, **kwargs):
        assert "TYPESAFE_API_KEY" not in kwargs["env"]
        assert "OTHER_API_KEY" not in kwargs["env"]
        return SimpleNamespace(stdout="ok")
    monkeypatch.setattr(cluster.subprocess, "run", run)
    assert cluster.command(["docker", "version"], capture=True) == "ok"
