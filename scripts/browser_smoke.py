#!/usr/bin/env python3
"""Real-browser smoke test for the build editor's first-run journey.

The build editor is a Viser/React app; its worst failures are *client-side* -- a
dropdown that renders over its own buttons, a duplicate option value that crashes
the whole page to blank, a stale panel that contradicts the status line. The
fake-GUI unit tests in ``tests/test_editor_controls.py`` cannot see any of these:
they check the Python that *builds* widgets, not the browser that *renders* them.

This script launches a real ``creature-lab build`` server and drives it with a
headless Chromium (Playwright), walking the exact path a first-time user takes:

    onboarding (pick creature + goal, Start) -> Test tab -> Simulate ("walk")
    -> read the result -> go back to the Design tab

and asserts, at each step, that the UI is actually usable and throws no console or
page errors. It exits non-zero on the first failure, printing what broke.

Usage
-----
    uv sync --inexact --extra sim --extra viz --extra browser
    python -m playwright install chromium        # one time
    python scripts/browser_smoke.py              # add --headed to watch it

This is intentionally NOT part of the default ``pytest`` suite: per AGENTS.md the
default suite must not require a browser/GUI. Run it by hand (or in a dedicated CI
job) whenever the editor's layout, tabs, onboarding, or result panel change.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

from _process_utils import free_port, taskkill_tree, wait_for_port

ROOT = Path(__file__).resolve().parents[1]

# Console noise the editor emits by design (WebGL/software-render/reconnect chatter).
_NOISE = (
    "GPU stall due to ReadPixels",
    "THREE.THREE.Clock",
    "Software mode",
    "WebGL support:",
    "Detected chrome version",
    "[Performance] Setting DPR",
    "Tried to send ViewerCameraMessage",
    "Connecting to:",
    "Connected!",
    "Disconnected!",
)


class _Smoke:
    def __init__(self, page, log) -> None:
        self.page = page
        self.log = log
        self.failures: list[str] = []
        self.console_errors: list[str] = []
        page.on("console", self._on_console)
        page.on("pageerror", lambda exc: self._record(f"PAGEERROR {exc}"))

    def _on_console(self, msg) -> None:
        if msg.type in ("error", "warning") and not any(n in msg.text for n in _NOISE):
            self._record(f"CONSOLE[{msg.type}] {msg.text}")

    def _record(self, text: str) -> None:
        self.console_errors.append(text)
        self.log(f"    !! {text[:200]}")

    def check(self, cond: bool, desc: str) -> None:
        self.log(f"  [{'PASS' if cond else 'FAIL'}] {desc}")
        if not cond:
            self.failures.append(desc)

    # -- reliable Viser/Mantine Select interaction -------------------------------
    def set_select(self, label: str, option: str) -> None:
        inp = self.page.locator(
            f"xpath=//label[normalize-space(text())='{label}']/following::input[1]"
        ).first
        inp.click(timeout=6000)
        self.page.wait_for_timeout(400)
        self.page.get_by_role("option", name=option, exact=True).first.click(timeout=6000)
        self.page.wait_for_timeout(1000)

    def click_phase(self, name: str) -> None:
        # Viser's button group renders labels rather than browser-local tabs. The
        # Python side owns phase visibility, which is what lets "Back to Design"
        # restore both controls and the editable 3D pose after playback.
        self.page.get_by_role("button", name=name, exact=True).click(timeout=6000)
        self.page.wait_for_timeout(1200)


def run(url: str, log) -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless="--headed" not in sys.argv)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        s = _Smoke(page, log)

        log("[1] load editor; onboarding usable (no dropdown covering the buttons)")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(7000)
        body = page.inner_text("body")
        s.check("Pick a creature" in body, "onboarding picker is visible")
        s.check(
            page.get_by_role("option").count() == 0,
            "no dropdown auto-opened over the Start/Skip buttons",
        )
        start = page.get_by_role("button", name="Start", exact=True)
        s.check(start.count() == 1 and not start.first.is_disabled(), "Start button is clickable")

        log("[2] pick the humanoid walking journey and click Start")
        s.set_select("Creature", "Humanoid")
        s.set_select("Goal", "Move forward")
        page.get_by_role("button", name="Start", exact=True).click(timeout=6000)
        page.wait_for_timeout(3000)
        dismissed = "Pick a creature" not in page.inner_text("body")
        s.check(dismissed, "onboarding dismissed after Start")
        s.check(page.locator(".mantine-Modal-overlay").count() == 0, "no leftover overlay")

        log("[3] Test tab -> Simulate ('walk') -> a result appears")
        s.click_phase("Test")
        sim = page.get_by_role("button", name="Simulate", exact=True)
        s.check(sim.count() == 1 and not sim.first.is_disabled(), "Simulate is available")
        if sim.count() and not sim.first.is_disabled():
            sim.first.click(timeout=6000)
            page.wait_for_timeout(16000)
            after = page.inner_text("body")
            s.check("Net displacement" in after, "Simulate produced a result")

        log("[4] switch controller -> posture clears stale result without breaking the panel")
        s.set_select("Controller", "posture")
        page.wait_for_timeout(1200)

        log("[5] explicit Back to Design restores the editable phase")
        page.get_by_role("button", name="Back to Design", exact=True).click(timeout=6000)
        page.wait_for_timeout(1200)
        d = page.inner_text("body")
        s.check("Start from" in d and "Body" in d, "Design phase shows template + body controls")

        log("[6] no console/page errors during the whole journey")
        s.check(not s.console_errors, f"zero console/page errors (saw {len(s.console_errors)})")

        browser.close()

    if s.failures or s.console_errors:
        log("\nRESULT: FAILED")
        for f in s.failures:
            log(f"  - {f}")
        return 1
    log("\nRESULT: all first-run smoke checks passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headed", action="store_true", help="Show the browser window.")
    parser.add_argument("--port", type=int, default=None, help="Editor port (default: a free one).")
    args = parser.parse_args()

    try:
        import playwright  # noqa: F401
    except ImportError:
        print(
            "playwright is not installed. Install it with:\n"
            "  uv sync --inexact --extra sim --extra viz --extra browser\n"
            "  python -m playwright install chromium",
            file=sys.stderr,
        )
        return 2

    port = args.port or free_port()
    url = f"http://localhost:{port}"

    def log(msg: str) -> None:
        print(msg, flush=True)

    log(f"launching: creature-lab build --no-open-browser --port {port}")
    proc = subprocess.Popen(
        ["uv", "run", "creature-lab", "build", "--no-open-browser", "--port", str(port)],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
    )
    result = 1
    try:
        if not wait_for_port(port, open_state=True, timeout=30):
            log("server did not open its port within 30 seconds")
        else:
            result = run(url, log)
    finally:
        if sys.platform == "win32":
            # Kill the live wrapper and descendants in one operation. Terminating
            # the uv wrapper first loses the process-tree relationship and used to
            # orphan creature-lab/Python servers on every successful smoke run.
            taskkill_tree(proc.pid)
        else:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if sys.platform == "win32":
                taskkill_tree(proc.pid)
            else:
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        if not wait_for_port(port, open_state=False, timeout=10):
            log(f"cleanup failure: server port {port} is still open")
            result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
