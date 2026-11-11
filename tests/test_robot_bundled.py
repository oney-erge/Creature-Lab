"""Robots that ship as a bundled pack: Unitree's H1 and H1-2, run from a robot.toml."""

from __future__ import annotations

import time

import numpy as np
import pytest
from pack_helpers import EXAMPLE

from creature_lab.robots import fetch
from creature_lab.robots.catalog import builtin_robots, robot_info
from creature_lab.robots.pack import (
    PackError,
    bundled_keys,
    bundled_pack,
    parse_pack,
    sync_bundled,
)
from creature_lab.robots.policies import RecurrentNpzPolicy

BUNDLED = ("unitree_h1", "unitree_h1_2")


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATURE_LAB_ROBOTS_DIR", str(tmp_path / "cache"))
    return tmp_path / "cache"


def test_the_bundled_robots_are_listed_after_the_hand_written_ones():
    assert tuple(bundled_keys()) == BUNDLED
    assert list(builtin_robots()) == ["microduck", "unitree_g1", *BUNDLED]


@pytest.mark.parametrize("key", BUNDLED)
def test_a_bundled_pack_describes_a_policy_that_fits_it(key):
    spec = bundled_pack(key).spec
    info = robot_info(key)
    assert info.pack and info.folder is None and info.manifest == f"{key}.json"
    assert info.first_run_s > 0 and info.credit and "BSD 3-Clause" in info.license_notice
    from importlib import resources

    weights = resources.files("creature_lab.robots").joinpath("data", "packs", key, "policy.npz")
    with resources.as_file(weights) as file:
        policy = RecurrentNpzPolicy(file)
    assert policy.obs_len == spec.observation_length()
    assert policy.action_len == len(spec.joints)


# Unitree's own TorchScript motion.pt: three steps of one run, each fed
# obs = linspace(-1, 1, n) x (1 + 0.1 x step).
EXPECTED = {
    "unitree_h1": [
        [-0.115769, 0.070927, -3.642257, 1.433483, -1.854975]
        + [-0.152855, -0.736153, -0.779533, 1.228399, -0.212497],
        [0.108231, 0.957506, -3.757594, 0.279673, -1.145326]
        + [-1.116919, -0.520183, -0.729601, 1.754927, -0.391872],
        [-0.453104, 2.774891, -4.434525, -1.054704, -0.049477]
        + [-0.100843, -2.760303, 0.189024, 2.163915, -0.165643],
    ],
    "unitree_h1_2": [
        [-0.546124, -0.232082, 0.911993, -1.413661, 3.36084, 0.037663]
        + [-0.342442, -0.408854, 1.513663, -0.720804, 2.468865, 2.128741],
        [-0.847162, -0.864704, 2.645554, -1.77196, 3.23075, 0.264648]
        + [-0.366702, -0.472151, 1.929219, -0.011178, -0.179268, 3.993885],
        [-0.879007, -1.388143, 3.92999, -1.948042, 3.215766, 1.741695]
        + [-0.438079, -0.419386, 1.831836, 1.486269, -0.03999, 3.090991],
    ],
}


@pytest.mark.parametrize("key", BUNDLED)
def test_the_converted_policy_matches_unitrees_torchscript_outputs(key):
    from importlib import resources

    weights = resources.files("creature_lab.robots").joinpath("data", "packs", key, "policy.npz")
    with resources.as_file(weights) as file:
        policy = RecurrentNpzPolicy(file)
    for step, expected in enumerate(EXPECTED[key]):
        obs = np.linspace(-1, 1, policy.obs_len).astype(np.float32) * (1 + 0.1 * step)
        assert np.allclose(policy.act(obs.astype(np.float64)), expected, atol=2e-5), (key, step)


def test_the_files_are_copied_beside_the_download_and_only_when_they_differ(cache):
    folder = sync_bundled("unitree_h1")
    assert folder == cache / "unitree_h1"
    assert {p.name for p in folder.iterdir()} == {"robot.toml", "policy.npz", "LICENSE.txt"}
    stamp = (folder / "policy.npz").stat().st_mtime_ns
    time.sleep(0.02)
    sync_bundled("unitree_h1")
    assert (folder / "policy.npz").stat().st_mtime_ns == stamp  # nothing rewritten

    (folder / "robot.toml").write_text("stale", encoding="utf-8")
    (folder / "meshes").mkdir()
    (folder / "meshes" / "keep.STL").write_bytes(b"downloaded")
    sync_bundled("unitree_h1")
    assert "unitree_h1" in (folder / "robot.toml").read_text(encoding="utf-8")  # restored
    assert (folder / "meshes" / "keep.STL").read_bytes() == b"downloaded"  # downloads untouched


def test_a_bundled_robot_is_ready_only_once_its_model_is_downloaded(cache, monkeypatch):
    assert not fetch.is_installed("unitree_h1")
    assert not (cache / "unitree_h1" / "robot.toml").exists()  # nothing copied for a robot not here
    monkeypatch.setattr(fetch, "load_manifest", lambda info: {"files": []})  # as if downloaded
    assert fetch.is_installed("unitree_h1")
    assert (cache / "unitree_h1" / "robot.toml").is_file()  # and now its pack files are in place


def test_ensure_robot_copies_the_pack_files_after_downloading(cache, monkeypatch):
    monkeypatch.setattr(fetch, "load_manifest", lambda info: {"files": []})
    assert fetch.ensure_robot("unitree_h1_2") == cache / "unitree_h1_2"
    assert (cache / "unitree_h1_2" / "policy.npz").is_file()


@pytest.mark.parametrize("key", BUNDLED)
def test_a_users_pack_cannot_take_a_bundled_robots_key(key):
    text = (EXAMPLE / "robot.toml").read_text(encoding="utf-8")
    with pytest.raises(PackError, match="built-in robot"):
        parse_pack(text.replace('key = "stick_biped"', f'key = "{key}"'))


# ---- the real robots: skipped unless they are downloaded (`robots fetch unitree-h1`) --------

mujoco = pytest.importorskip("mujoco")


@pytest.mark.parametrize("key", BUNDLED)
def test_unitrees_policy_walks_the_robot_without_falling(key):
    if not fetch.is_installed(key):
        pytest.skip(f"{key} not downloaded")
    from creature_lab.robots.analysis import analyze
    from creature_lab.robots.api import run_scenario
    from creature_lab.robots.types import Scenario

    run = run_scenario(Scenario(robot=key, policy="motion", command=0.5))
    result = analyze(run)
    assert not result.fell and result.distance_m > 2.0
    assert run.provenance["robot"] == key and len(run.provenance["policy_sha256"]) == 64
