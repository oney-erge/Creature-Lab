"""Record scenes of the real Creature Lab app with CDP screencast, for the README GIF and the tour.

Each scene writes JPEG frames plus the browser's own frame timestamps
(outputs/media-recording/frames/<scene>/times.json) and named marks (marks.json) that
compose_app.py cuts on. Nothing is staged: the app runs on saved check-ups, or (scene "firstrun")
downloads and checks up the G1 from an empty robot cache.

    # saved results (both robots checked up), and a copy without saved "what if" runs
    creature-lab app --port 8765 --no-open-browser --checkups <results>
    # an empty cache and no results, for the first run
    export CREATURE_LAB_ROBOTS_DIR=<empty>
    creature-lab app --port 8766 --no-open-browser --checkups <empty2>
    python scripts/media/record_app.py firstrun http://127.0.0.1:8766/
    python scripts/media/record_app.py fall|whatif|policies|overview http://127.0.0.1:8765/

Needs the `browser` extra. Uses Microsoft Edge when installed (it renders WebGL on the real GPU
in headless mode), else Playwright's Chromium.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

HERE = Path(
    os.environ.get("CREATURE_LAB_MEDIA_DIR")
    or Path(__file__).resolve().parents[2] / "outputs" / "media-recording"
)
VIEW = {"width": 1280, "height": 648}
SCALE = 1.5  # frames are 1920x972
ZOOM = float(os.environ.get("REC_ZOOM", "-350"))  # scroll-zoom of the 3D camera before a scene

CURSOR_JS = r"""
(() => {
  const ARROW = 'M4 2 L4 19 L8.5 15 L11.5 22 L14.5 20.7 L11.6 14 L17.5 14 Z';
  const install = () => {
    if (document.getElementById('__cursor')) return;
    const c = document.createElement('div');
    c.id = '__cursor';
    c.innerHTML = `<svg width="26" height="26" viewBox="0 0 24 24"><path d="${ARROW}"
      fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>`;
    Object.assign(c.style, {position: 'fixed', left: '-40px', top: '-40px',
      zIndex: 2147483647, pointerEvents: 'none',
      filter: 'drop-shadow(0 2px 3px rgba(0,0,0,.5))'});
    document.documentElement.appendChild(c);
    const ring = document.createElement('div');
    Object.assign(ring.style, {position: 'fixed', width: '44px', height: '44px',
      marginLeft: '-22px', marginTop: '-22px', borderRadius: '50%',
      border: '3px solid #ff8a3d', zIndex: 2147483646, pointerEvents: 'none',
      opacity: '0', transform: 'scale(.3)'});
    document.documentElement.appendChild(ring);
    addEventListener('mousemove', (e) => {
      c.style.left = e.clientX - 4 + 'px';
      c.style.top = e.clientY - 2 + 'px';
    }, true);
    addEventListener('mousedown', (e) => {
      ring.style.left = e.clientX + 'px';
      ring.style.top = e.clientY + 'px';
      ring.animate([{opacity: 1, transform: 'scale(.3)'}, {opacity: 0, transform: 'scale(1.4)'}],
                   {duration: 550, easing: 'ease-out'});
    }, true);
  };
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', install);
  else install();
})();
"""


class Recorder:
    def __init__(self, page: Page, scene: str) -> None:
        self.page = page
        self.dir = HERE / "frames" / scene
        self.dir.mkdir(parents=True, exist_ok=True)
        for old in self.dir.glob("*.jpg"):
            old.unlink()
        self.times: list[tuple[float, str]] = []
        self.marks: list[tuple[str, float]] = []
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._frame)
        self.mouse = (VIEW["width"] / 2, VIEW["height"] / 2)

    def _frame(self, params: dict) -> None:
        name = f"{len(self.times):05d}.jpg"
        (self.dir / name).write_bytes(base64.b64decode(params["data"]))
        self.times.append((params["metadata"]["timestamp"], name))
        try:
            self.cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
        except Exception:
            pass

    def start(self) -> None:
        w, h = int(VIEW["width"] * SCALE), int(VIEW["height"] * SCALE)
        self.cdp.send(
            "Page.startScreencast",
            {"format": "jpeg", "quality": 92, "maxWidth": w, "maxHeight": h, "everyNthFrame": 2},
        )
        self.mark("start")

    def stop(self) -> None:
        self.mark("end")
        self.cdp.send("Page.stopScreencast")
        (self.dir / "times.json").write_text(json.dumps(self.times))
        (self.dir / "marks.json").write_text(json.dumps(self.marks, indent=1))
        span = self.times[-1][0] - self.times[0][0] if self.times else 0
        print(
            f"{self.dir.name}: {len(self.times)} frames over {span:.1f} s "
            f"({len(self.times) / max(span, 1e-6):.0f} fps)"
        )

    def mark(self, name: str) -> None:
        self.marks.append((name, time.time()))

    def hold(self, seconds: float) -> None:
        self.page.wait_for_timeout(int(seconds * 1000))

    def glide(self, x: float, y: float, seconds: float = 0.6) -> None:
        x0, y0 = self.mouse
        steps = max(2, int(seconds * 60))
        for i in range(1, steps + 1):
            t = i / steps
            e = t * t * (3 - 2 * t)  # smoothstep
            self.page.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e)
            self.page.wait_for_timeout(16)
        self.mouse = (x, y)

    def click(self, locator, mark: str | None = None, settle: float = 0.25) -> None:
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        assert box, f"not visible: {locator}"
        self.glide(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        self.hold(settle)
        if mark:
            self.mark(mark)
        self.page.mouse.down()
        self.page.wait_for_timeout(60)
        self.page.mouse.up()

    def seek(self, seconds: float, duration: float) -> None:
        """Click the timeline at a moment of the run (the chart is a draggable playhead)."""
        bar = self.page.get_by_label("Playback position")
        box = bar.bounding_box()
        assert box
        x = box["x"] + box["width"] * seconds / duration
        self.page.mouse.click(x, box["y"] + box["height"] / 2)


def open_page(p, url: str):
    # Screencast frames come at CSS size unless the whole browser renders at 1.5x.
    args = [f"--force-device-scale-factor={SCALE}"]
    try:
        angle = ["--use-angle=d3d11"] if sys.platform == "win32" else []
        browser = p.chromium.launch(channel="msedge", headless=True, args=[*args, *angle])
    except Exception:
        browser = p.chromium.launch(headless=True, args=args)
    context = browser.new_context(viewport=VIEW, device_scale_factor=SCALE, color_scheme="dark")
    context.add_init_script(CURSOR_JS)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.goto(url)
    return browser, page, errors


def zoom_stage(page: Page, testid: str = "stage", delta: float = -500) -> None:
    """Scroll-zoom the 3D camera in, as a user would, then park the mouse off the canvas."""
    box = page.get_by_test_id(testid).bounding_box()
    assert box
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    for _ in range(5):
        page.mouse.wheel(0, delta / 5)
        page.wait_for_timeout(60)
    page.wait_for_timeout(400)


def show_verdict(page: Page) -> None:
    """Scroll the side panel so the comparison sentence is in view (the payoff of a pair)."""
    page.get_by_test_id("verdict").evaluate("el => el.scrollIntoView({block: 'start'})")
    page.wait_for_timeout(300)


# ---- scenes -----------------------------------------------------------------------------------
def scene_firstrun(page: Page, rec: Recorder) -> None:
    page.get_by_test_id("hero").wait_for()
    page.get_by_role("button", name="Download and check up").wait_for()
    rec.hold(2.5)  # let the bundled clip start
    rec.start()
    rec.mark("hero")
    rec.hold(3.0)
    rec.click(page.get_by_role("button", name="Download and check up"), "license")
    rec.hold(2.2)
    rec.click(page.get_by_role("checkbox"), "agree")
    rec.hold(0.6)
    rec.click(page.get_by_role("button", name="Download and run the check-up"), "accepted")
    # The real download and check-up; the app opens the results by itself when it is done.
    page.get_by_test_id("stage").wait_for(timeout=240_000)
    rec.mark("results")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=stage]')?.dataset.state === 'ready'",
        timeout=60_000,
    )
    rec.mark("ready")
    rec.hold(9.0)
    rec.stop()


def scene_fall(page: Page, rec: Recorder) -> None:
    """G1, 150 N shove: the fall, slowed down, and the explanation beside it."""
    page.get_by_text("Unitree G1", exact=True).first.click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=stage]')?.dataset.state === 'ready'",
        timeout=60_000,
    )
    page.get_by_role("button", name="Pause").click()
    zoom_stage(page, "stage", ZOOM)
    rec.hold(0.5)
    rec.seek(2.6, 10.0)
    rec.hold(0.8)
    rec.start()
    rec.mark("paused")
    rec.hold(0.8)
    rec.click(page.get_by_role("button", name="Play"), "play")
    rec.hold(13.0)
    rec.mark("why")
    rec.hold(1.0)
    rec.stop()


def scene_whatif(page: Page, rec: Recorder) -> None:
    """G1, 150 N shove: ask for a gentler shove, it runs, and plays beside the original."""
    page.get_by_text("Unitree G1", exact=True).first.click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=stage]')?.dataset.state === 'ready'",
        timeout=60_000,
    )
    page.get_by_role("button", name="Pause").click()
    page.get_by_role("button", name="A gentler shove").scroll_into_view_if_needed()
    rec.hold(0.8)
    rec.start()
    rec.mark("ask")
    rec.hold(1.2)
    rec.click(page.get_by_role("button", name="A gentler shove"), "clicked")
    page.get_by_test_id("pair").wait_for(timeout=120_000)
    rec.mark("pair")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=stage-b]')?.dataset.state === 'ready'",
        timeout=60_000,
    )
    rec.mark("pair-ready")
    page.get_by_role("button", name="Pause").click()
    show_verdict(page)
    rec.seek(3.0, 10.0)
    rec.glide(640, 600, 0.5)
    rec.hold(0.8)
    rec.click(page.get_by_role("button", name="Play"), "play")
    rec.glide(640, 610, 0.4)
    rec.hold(12.0)
    rec.stop()


def scene_policies(page: Page, rec: Recorder) -> None:
    """Microduck, 3 N shove: the walk-only policy beside Pollen's walk + get-up policy."""
    page.get_by_text("Microduck", exact=True).first.click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=stage]')?.dataset.state === 'ready'",
        timeout=60_000,
    )
    page.get_by_role("button", name="Pause").click()
    rec.hold(0.5)
    rec.start()
    rec.mark("one")
    rec.hold(1.0)
    rec.click(page.get_by_role("button", name="See both side by side"), "both")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=stage-b]')?.dataset.state === 'ready'",
        timeout=60_000,
    )
    page.get_by_role("button", name="Pause").click()
    show_verdict(page)
    rec.seek(3.4, 10.0)
    rec.glide(640, 600, 0.5)
    rec.hold(0.8)
    rec.click(page.get_by_role("button", name="Play"), "play")
    rec.glide(640, 610, 0.4)
    rec.hold(12.0)
    rec.stop()


def scene_overview(page: Page, rec: Recorder) -> None:
    """G1: the check-up grid of every shove strength and moment."""
    page.get_by_text("Unitree G1", exact=True).first.click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=stage]')?.dataset.state === 'ready'",
        timeout=60_000,
    )
    grid = page.get_by_text("Shoves that leave it on the floor", exact=False).first
    rec.hold(0.5)
    rec.start()
    rec.mark("top")
    rec.hold(0.8)
    grid.evaluate(
        "el => el.closest('.panel').scrollIntoView({behavior: 'smooth', block: 'center'})"
    )
    rec.hold(1.2)
    rec.mark("grid")
    row = page.get_by_role("button", name="Watch").nth(2)
    rec.click(row, "watch")
    rec.hold(4.0)
    rec.stop()


SCENES = {
    "firstrun": scene_firstrun,
    "fall": scene_fall,
    "whatif": scene_whatif,
    "policies": scene_policies,
    "overview": scene_overview,
}

if __name__ == "__main__":
    scene, url = sys.argv[1], sys.argv[2]
    with sync_playwright() as p:
        browser, page, errors = open_page(p, url)
        rec = Recorder(page, scene)
        try:
            SCENES[scene](page, rec)
        finally:
            if rec.times and not (rec.dir / "times.json").exists():
                rec.stop()
            print("page errors:", errors or "none")
            browser.close()
