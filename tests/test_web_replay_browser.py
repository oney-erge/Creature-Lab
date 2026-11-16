"""Opt-in browser check for saved replay and responsive comparison layout."""

from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

if os.environ.get("CREATURE_LAB_BROWSER_REPLAY") != "1":
    pytest.skip(
        "set CREATURE_LAB_BROWSER_REPLAY=1 for the browser replay check", allow_module_level=True
    )

uvicorn = pytest.importorskip("uvicorn")
mujoco = pytest.importorskip("mujoco")
playwright = pytest.importorskip("playwright.sync_api")

from robot_helpers import saved_checkup  # noqa: E402
from test_web_server import ROBOT_XML  # noqa: E402

from creature_lab.web import scene, server  # noqa: E402


class _Server:
    def __init__(self, app):
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(128)
        self.address = f"http://127.0.0.1:{self.socket.getsockname()[1]}"
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        self.thread = threading.Thread(
            target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True
        )

    def __enter__(self):
        self.thread.start()
        deadline = time.monotonic() + 20
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() >= deadline:
                self.server.should_exit = True
                self.thread.join(timeout=10)
                self.socket.close()
                raise RuntimeError("Fixture server did not start")
            time.sleep(0.05)
        return self.address

    def __exit__(self, *_args):
        self.server.should_exit = True
        self.thread.join(timeout=10)
        self.socket.close()
        if self.thread.is_alive():
            raise RuntimeError("Fixture server did not stop")


def _overlap(stage, first: str, second: str) -> bool:
    return stage.evaluate(
        """(el, selectors) => {
          const first = el.querySelector(selectors[0]), second = el.querySelector(selectors[1]);
          if (!first || !second) return false;
          const a = first.getBoundingClientRect(), b = second.getBoundingClientRect();
          return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
        }""",
        [first, second],
    )


def test_saved_replay_and_comparison_survive_restart_without_new_work(tmp_path: Path, monkeypatch):
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        user_temp = (local / "Temp").resolve()
        scratch = Path(tempfile.gettempdir()).resolve()
        if scratch == user_temp or scratch.is_relative_to(user_temp):
            pytest.fail("Set TEMP and TMP to a scratch directory outside Windows user Temp")
    root = tmp_path / "checkup"
    unitree = root / "unitree_g1-fixture"
    duck = root / "microduck-fixture"
    saved_checkup(unitree / "motion", "motion", stays_down=True, robot="unitree_g1", qpos_width=8)
    saved_checkup(duck / "alpha_walking", "alpha_walking", stays_down=True, qpos_width=8)
    saved_checkup(duck / "velstand", "velstand", stays_down=False, qpos_width=8)
    monkeypatch.setattr(server, "is_installed", lambda _key: True)
    monkeypatch.setattr(server, "missing_extra", lambda: [])
    monkeypatch.setattr(
        scene, "_load_model", lambda _robot: mujoco.MjModel.from_xml_string(ROBOT_XML)
    )
    scene.load_scene.cache_clear()

    blocked: list[str] = []
    pose_statuses: list[int] = []
    allowed_origin = [""]
    try:
        with playwright.sync_playwright() as browser_api:
            browser = browser_api.chromium.launch(
                headless=True, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
            )
            context = browser.new_context(
                viewport={"width": 1440, "height": 900}, reduced_motion="reduce"
            )

            def guard(route):
                request = route.request
                if request.method not in ("GET", "HEAD") or not request.url.startswith(
                    allowed_origin[0] + "/"
                ):
                    blocked.append(f"{request.method} {request.url}")
                    route.abort()
                elif "/thumbnail" in request.url:
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", guard)
            page = context.new_page()
            page.on(
                "response",
                lambda response: (
                    pose_statuses.append(response.status) if "/poses" in response.url else None
                ),
            )

            def replay(origin: str, robot: str, *, comparison: bool) -> str:
                allowed_origin[0] = origin
                page.goto(f"{origin}/#/robots/{robot}", wait_until="domcontentloaded")
                if comparison:
                    page.get_by_role("button", name="See both side by side").click(timeout=30000)
                    playwright.expect(page.get_by_test_id("pair")).to_be_visible()
                stages = page.locator(".pair .stage" if comparison else '[data-testid="stage"]')
                playwright.expect(stages).to_have_count(2 if comparison else 1, timeout=30000)
                for stage in stages.all():
                    playwright.expect(stage).to_have_attribute("data-state", "ready", timeout=30000)
                    playwright.expect(stage.locator(".hud.lite")).to_be_visible()
                    assert not _overlap(stage, ".hud.lite", ".hud.tl")
                    assert not _overlap(stage, ".hud.lite", ".hud.tr")
                    assert not _overlap(stage, ".hud.lite", ".key3d")
                if comparison:
                    stage_bottom = max(
                        stage.bounding_box()["y"] + stage.bounding_box()["height"]
                        for stage in stages.all()
                    )
                    assert stage_bottom <= page.locator(".timeline").bounding_box()["y"]
                page.wait_for_function(
                    "() => document.querySelector('[aria-label=\"Playback position\"]')?.max > 1",
                    timeout=20000,
                )
                play = page.get_by_role("button", name="Play", exact=True)
                playwright.expect(play).to_be_enabled(timeout=20000)
                play.focus()
                page.keyboard.press("Space")
                playwright.expect(
                    page.get_by_role("button", name="Pause", exact=True)
                ).to_be_visible()
                page.wait_for_function(
                    "() => Number(document.querySelector("
                    "'[aria-label=\"Playback position\"]')?.value) > 0.1",
                    timeout=10000,
                )
                page.get_by_role("button", name="Pause", exact=True).focus()
                page.keyboard.press("Space")
                playwright.expect(
                    page.get_by_role("button", name="Play", exact=True)
                ).to_be_visible()
                return page.get_by_test_id("stage").get_attribute("data-run")

            with _Server(server.create_app(root)) as first:
                single_id = replay(first, "unitree_g1", comparison=False)
                pair_id = replay(first, "microduck", comparison=True)
            page.set_viewport_size({"width": 390, "height": 844})
            with _Server(server.create_app(root)) as second:
                assert replay(second, "unitree_g1", comparison=False) == single_id
                assert replay(second, "microduck", comparison=True) == pair_id
            assert not blocked
            assert len(pose_statuses) >= 4 and all(status == 200 for status in pose_statuses)
            context.close()
            browser.close()
    finally:
        scene.load_scene.cache_clear()
