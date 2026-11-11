"""Downloads are verified against pinned hashes and never leave a bad file behind."""

import hashlib
from types import SimpleNamespace

import pytest

from creature_lab.robots import fetch


@pytest.fixture
def source(tmp_path, monkeypatch):
    """A fake robot served from local files, with the cache redirected into tmp_path."""
    served = tmp_path / "served"
    served.mkdir()
    (served / "model.xml").write_bytes(b"<mujoco/>")
    (served / "mesh.stl").write_bytes(b"solid mesh")
    monkeypatch.setenv("CREATURE_LAB_ROBOTS_DIR", str(tmp_path / "cache"))

    def entry(name):
        data = (served / name).read_bytes()
        return {
            "path": f"assets/{name}",
            "url": (served / name).as_uri(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }

    manifest = {"files": [entry("model.xml"), entry("mesh.stl")]}
    monkeypatch.setattr(fetch, "load_manifest", lambda info: manifest)
    monkeypatch.setattr(fetch, "robot_info", lambda key: SimpleNamespace(key=key, folder=None))
    return served, manifest


def test_missing_files_are_downloaded_and_verified(source):
    _, manifest = source
    assert not fetch.is_installed("fake")
    folder = fetch.ensure_robot("fake")
    assert (folder / "assets" / "model.xml").read_bytes() == b"<mujoco/>"
    assert fetch.is_installed("fake")
    assert fetch.missing_files(SimpleNamespace(key="fake")) == []
    assert len(manifest["files"]) == 2


def test_a_second_run_downloads_nothing(source):
    fetch.ensure_robot("fake")
    messages = []
    fetch.ensure_robot("fake", progress=messages.append)
    assert messages == []


def test_a_tampered_file_is_detected_and_replaced(source):
    folder = fetch.ensure_robot("fake")
    (folder / "assets" / "mesh.stl").write_bytes(b"corrupted!")
    assert not fetch.is_installed("fake")
    fetch.ensure_robot("fake")
    assert (folder / "assets" / "mesh.stl").read_bytes() == b"solid mesh"


def test_a_hash_mismatch_is_refused_and_leaves_nothing(source):
    served, manifest = source
    (served / "model.xml").write_bytes(b"<evil/>")
    with pytest.raises(fetch.FetchError, match="pinned SHA-256"):
        fetch.ensure_robot("fake")
    folder = fetch.robot_dir("fake")
    assert not (folder / "assets" / "model.xml").exists()
    assert not list(folder.rglob("*.part"))


def test_an_unreachable_url_is_a_fetch_error(source):
    served, manifest = source
    (served / "model.xml").unlink()
    with pytest.raises(fetch.FetchError, match="could not download"):
        fetch.ensure_robot("fake")


def test_the_cache_never_lives_in_the_temp_folder(monkeypatch):
    monkeypatch.delenv("CREATURE_LAB_ROBOTS_DIR", raising=False)
    assert "temp" not in {part.lower() for part in fetch.cache_root().parts}
