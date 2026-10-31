"""Catalog and download-manifest invariants: pinned sources, hashes, and license notices."""

import re
from importlib import resources

import pytest

from creature_lab.robots.catalog import ROBOTS, load_manifest, robot_info

COMMIT_URL = re.compile(r"https://[^/]+/.+/[0-9a-f]{40}/")


@pytest.mark.parametrize("key", [key for key, info in ROBOTS.items() if info.manifest])
def test_manifest_files_are_pinned_and_hashed(key):
    manifest = load_manifest(robot_info(key))
    assert manifest["files"], "a robot with a manifest must download something"
    paths = [entry["path"] for entry in manifest["files"]]
    assert len(paths) == len(set(paths))
    for entry in manifest["files"]:
        assert entry["url"].startswith("https://")
        assert COMMIT_URL.match(entry["url"]), f"{entry['url']} is not pinned to a commit"
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
        assert entry["bytes"] > 0
        assert ".." not in entry["path"] and not entry["path"].startswith("/")


def test_every_policy_file_is_in_the_manifest():
    for info in ROBOTS.values():
        listed = {entry["path"] for entry in load_manifest(info)["files"]}
        for policy in info.policies:
            if policy.file is not None:
                assert policy.file in listed


def test_default_policy_exists():
    for info in ROBOTS.values():
        assert info.policy(info.default_policy).key == info.default_policy


def test_unknown_policy_lists_the_choices():
    with pytest.raises(KeyError, match="velstand"):
        robot_info("microduck").policy("nope")


def test_microduck_notice_names_the_non_commercial_mesh_license():
    info = robot_info("microduck")
    assert info.non_commercial
    assert "CC BY-NC-SA 4.0" in info.license_notice
    assert "CC BY-NC-SA 4.0" in info.credit
    assert "never bundles" in info.license_notice


def test_no_microduck_mesh_is_bundled_in_the_package():
    data = resources.files("creature_lab.robots").joinpath("data")
    names = [item.name.lower() for item in data.iterdir()]
    assert not any(name.endswith((".stl", ".obj")) for name in names)


def test_bundled_g1_policy_ships_with_its_license():
    data = resources.files("creature_lab.robots").joinpath("data")
    assert data.joinpath("unitree_g1_policy.npz").is_file()
    assert "BSD 3-Clause" in data.joinpath("UNITREE_RL_GYM_LICENSE.txt").read_text("utf-8")
