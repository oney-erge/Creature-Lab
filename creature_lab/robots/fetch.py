"""Download robot files into a per-user cache, verifying each against a pinned SHA-256."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from creature_lab.robots.catalog import RobotInfo, load_manifest, robot_info

_CHUNK = 1 << 20
_TIMEOUT_S = 60
#: Tries per file. A robot is 20 to 60 files from raw.githubusercontent.com, and one dropped
#: connection ("forcibly closed by the remote host") used to fail the whole download.
_ATTEMPTS = 3
_BACKOFF_S = (1.0, 3.0)


class FetchError(RuntimeError):
    """A robot file could not be downloaded or did not match its pinned hash."""


#: Import name -> package name for what the check-up needs beyond the core install.
_EXTRA_PACKAGES = {
    "mujoco": "mujoco",
    "onnxruntime": "onnxruntime",
    "imageio": "imageio",
    "PIL": "pillow",
}


def missing_extra() -> list[str]:
    """Packages from the ``robots`` extra that are not installed."""
    return [
        package
        for module, package in _EXTRA_PACKAGES.items()
        if importlib.util.find_spec(module) is None
    ]


def cache_root() -> Path:
    """Per-user folder for downloaded robots (never inside the temp directory)."""
    override = os.environ.get("CREATURE_LAB_ROBOTS_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "creature-lab" / "robots"


def robot_dir(key: str) -> Path:
    """Where a robot's files are: the download cache, or a robot pack's own folder."""
    folder = robot_info(key).folder
    return folder if folder is not None else cache_root() / key


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def missing_files(info: RobotInfo) -> list[dict]:
    """Manifest entries that are absent or fail their hash check."""
    folder = robot_dir(info.key)
    bad = []
    for entry in load_manifest(info)["files"]:
        path = folder / entry["path"]
        if (
            not path.is_file()
            or path.stat().st_size != entry["bytes"]
            or _sha256(path) != entry["sha256"]
        ):
            bad.append(entry)
    return bad


def is_installed(key: str) -> bool:
    info = robot_info(key)
    if info.folder is not None:  # a robot pack: nothing to download, but its folder must exist
        return (info.folder / info.staging.model_file).is_file()
    if missing_files(info):
        return False
    if info.pack:  # a bundled pack: its robot.toml and policies come with the package
        from creature_lab.robots.pack import sync_bundled

        sync_bundled(key)
    return True


def _transient(error: OSError) -> bool:
    """A dropped connection, a timeout or a busy server is worth another try; a missing file not."""
    if isinstance(error, urllib.error.HTTPError):
        return error.code >= 500 or error.code == 429
    reason = getattr(error, "reason", error)
    return not isinstance(reason, (FileNotFoundError, PermissionError))


def _download(
    url: str, target: Path, expected_sha: str, sleep: Callable[[float], None] = time.sleep
) -> None:
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            _download_once(url, target, expected_sha)
            return
        except _Interrupted as interrupted:
            error = interrupted.__cause__
            if attempt == _ATTEMPTS or not isinstance(error, OSError) or not _transient(error):
                parts = urllib.parse.urlparse(url)
                tries = f" after {attempt} tries" if attempt > 1 else ""
                raise FetchError(
                    f"Could not download {Path(parts.path).name} from {parts.netloc}{tries} "
                    f"({error}). Check the connection and download again: the files already "
                    "fetched are kept."
                ) from error
            sleep(_BACKOFF_S[min(attempt, len(_BACKOFF_S)) - 1])


class _Interrupted(Exception):
    """One try at one file did not finish (its cause is the network error)."""


def _download_once(url: str, target: Path, expected_sha: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "creature-lab"})
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:  # noqa: S310
            with partial.open("wb") as handle:
                while chunk := response.read(_CHUNK):
                    digest.update(chunk)
                    handle.write(chunk)
    except OSError as error:
        partial.unlink(missing_ok=True)
        raise _Interrupted() from error
    if digest.hexdigest() != expected_sha:
        partial.unlink(missing_ok=True)
        raise FetchError(f"{url} does not match its pinned SHA-256; refusing to use it")
    partial.replace(target)


def ensure_robot(key: str, progress: Callable[[str], None] | None = None) -> Path:
    """Download whatever is missing for ``key`` and return its folder."""
    info = robot_info(key)
    folder = robot_dir(key)
    if info.folder is not None:
        return folder
    todo = missing_files(info)
    for index, entry in enumerate(todo, start=1):
        if progress:
            progress(f"[{index}/{len(todo)}] {entry['path']}")
        _download(entry["url"], folder / entry["path"], entry["sha256"])
    if info.pack:
        from creature_lab.robots.pack import sync_bundled

        sync_bundled(key)
    return folder
