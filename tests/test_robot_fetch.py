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
    monkeypatch.setattr(
        fetch, "robot_info", lambda key: SimpleNamespace(key=key, folder=None, pack=False)
    )
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
    with pytest.raises(fetch.FetchError, match="(?i)could not download"):
        fetch.ensure_robot("fake")


def test_the_cache_never_lives_in_the_temp_folder(monkeypatch):
    monkeypatch.delenv("CREATURE_LAB_ROBOTS_DIR", raising=False)
    assert "temp" not in {part.lower() for part in fetch.cache_root().parts}


def _flaky(fails: list[OSError]):
    """A _download_once that fails with these errors in turn, then succeeds."""
    calls = []

    def once(url, target, expected_sha):
        calls.append(url)
        if fails:
            raise fetch._Interrupted() from fails.pop(0)

    return once, calls


def test_a_dropped_connection_is_tried_again(monkeypatch, tmp_path):
    """One reset connection among a robot's 55 files used to fail the whole download."""
    once, calls = _flaky(
        [ConnectionResetError(10054, "forcibly closed"), TimeoutError("timed out")]
    )
    monkeypatch.setattr(fetch, "_download_once", once)
    waits = []
    fetch._download("https://host.test/a.stl", tmp_path / "a.stl", "0" * 64, sleep=waits.append)
    assert len(calls) == 3 and waits == [1.0, 3.0]


def test_a_download_that_keeps_failing_says_how_to_resume(monkeypatch, tmp_path):
    once, calls = _flaky([ConnectionResetError("reset")] * 3)
    monkeypatch.setattr(fetch, "_download_once", once)
    with pytest.raises(fetch.FetchError) as raised:
        fetch._download(
            "https://host.test/m/a.stl", tmp_path / "a.stl", "0" * 64, sleep=lambda s: None
        )
    assert len(calls) == 3
    message = str(raised.value)
    assert (
        "a.stl from host.test after 3 tries" in message
        and "files already fetched are kept" in message
    )


def test_a_missing_file_is_not_tried_again(monkeypatch, tmp_path):
    import urllib.error

    missing = urllib.error.HTTPError("https://host.test/a.stl", 404, "Not Found", None, None)
    once, calls = _flaky([missing])
    monkeypatch.setattr(fetch, "_download_once", once)
    with pytest.raises(fetch.FetchError):
        fetch._download(
            "https://host.test/a.stl", tmp_path / "a.stl", "0" * 64, sleep=lambda s: None
        )
    assert len(calls) == 1
