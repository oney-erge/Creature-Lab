"""Cut the scenes recorded by record_app.py into the tour video, the README GIF and the site loop.

Every caption number below was read off the recorded app (saved runs) or timed during the
recording (marks.json); nothing is invented. Speed-ups are said in the caption. Re-read the
captions against the frames (`still tour`) after every new recording: the numbers come from the
runs on screen, so a different check-up needs different words.

    python scripts/media/compose_app.py tour|gif|site|poster|still tour

Needs the `export` extra (imageio-ffmpeg, Pillow). Writes to outputs/media-recording/out.
"""

from __future__ import annotations

import bisect
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

HERE = Path(
    os.environ.get("CREATURE_LAB_MEDIA_DIR")
    or Path(__file__).resolve().parents[2] / "outputs" / "media-recording"
)
OUT = HERE / "out"
OUT.mkdir(parents=True, exist_ok=True)
UI_W, UI_H = 1920, 972
STRIP = 108
BG = (10, 14, 22)
ORANGE = (255, 138, 61)
MUTED = (154, 164, 178)
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
# Segoe UI on Windows (what the published media use), DejaVu elsewhere.
_SANS = {
    False: ["C:/Windows/Fonts/segoeui.ttf", "DejaVuSans.ttf"],
    True: ["C:/Windows/Fonts/segoeuib.ttf", "DejaVuSans-Bold.ttf"],
}
_MONO = ["C:/Windows/Fonts/consola.ttf", "DejaVuSansMono.ttf"]


def _first_font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return _first_font(_SANS[bold], size)


class Scene:
    def __init__(self, name: str) -> None:
        d = HERE / "frames" / name
        self.dir = d
        self.times = json.loads((d / "times.json").read_text())
        self.stamps = [t for t, _ in self.times]
        self.marks = dict(json.loads((d / "marks.json").read_text()))
        self._cache: tuple[int, Image.Image] | None = None

    def at(self, stamp: float) -> Image.Image:
        i = max(0, bisect.bisect_right(self.stamps, stamp) - 1)
        if self._cache and self._cache[0] == i:
            return self._cache[1]
        im = Image.open(self.dir / self.times[i][1]).convert("RGB")
        if im.size != (UI_W, UI_H):
            im = im.resize((UI_W, UI_H), Image.LANCZOS)
        self._cache = (i, im)
        return im


@dataclass
class Cut:
    scene: str
    mark: str
    start: float  # seconds after the mark
    end: float
    caption: str = ""
    note: str = ""  # small grey text under the caption (credit, speed-up)
    speed: float = 1.0
    fade: bool = False  # cross-fade in from the previous cut


@dataclass
class Card:
    kind: str  # "title" | "end"
    seconds: float


def wrap(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=f) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    return [*lines, line] if line else lines


def strip(caption: str, note: str, width: int = UI_W) -> Image.Image:
    im = Image.new("RGB", (width, STRIP), BG)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, width, 3), fill=(38, 46, 60))
    if not caption:
        return im
    d.rectangle((48, 26, 54, STRIP - 26), fill=ORANGE)
    room = width - 80 - 48
    for size in (40, 36, 32, 29):
        f = font(size, bold=True)
        lines = wrap(d, caption, f, room)
        if len(lines) <= (1 if note else 2):
            break
    nf = font(25)
    line_h = int(size * 1.22)
    block = line_h * len(lines) + (34 if note else 0)
    y = (STRIP - block) // 2 + 2
    for line in lines:
        d.text((76, y), line, font=f, fill=(244, 246, 250))
        y += line_h
    if note:
        d.text((76, y + 2), note, font=nf, fill=MUTED)
    return im


def card(kind: str) -> Image.Image:
    im = Image.new("RGB", (UI_W, UI_H + STRIP), BG)
    d = ImageDraw.Draw(im)
    cx = UI_W // 2
    if kind == "title":
        d.text((cx, 400), "Creature Lab", font=font(112, True), fill=(244, 246, 250), anchor="mm")
        d.text(
            (cx, 520),
            "Shove a real robot, see exactly why it fell, and prove the fix.",
            font=font(48),
            fill=(214, 220, 228),
            anchor="mm",
        )
        d.text(
            (cx, 600),
            "On a laptop, in a browser. Real robot models with their published policies.",
            font=font(34),
            fill=MUTED,
            anchor="mm",
        )
        d.rectangle((cx - 60, 668, cx + 60, 674), fill=ORANGE)
    else:
        d.text((cx, 330), "Creature Lab", font=font(96, True), fill=(244, 246, 250), anchor="mm")
        d.text(
            (cx, 440),
            "github.com/oney-erge/Creature-Lab",
            font=font(52, True),
            fill=ORANGE,
            anchor="mm",
        )
        mono = _first_font(_MONO, 38)
        d.rounded_rectangle((cx - 560, 520, cx + 560, 690), radius=18, fill=(20, 26, 38))
        d.text(
            (cx, 572),
            "git clone https://github.com/oney-erge/Creature-Lab",
            font=mono,
            fill=(214, 220, 228),
            anchor="mm",
        )
        d.text(
            (cx, 636),
            "cd Creature-Lab && ./run.sh      (Windows: run.bat)",
            font=mono,
            fill=(214, 220, 228),
            anchor="mm",
        )
        d.text(
            (cx, 770),
            "Free and open source (Apache-2.0). The physics runs on the CPU; "
            "it is a simulation, not the hardware.",
            font=font(30),
            fill=MUTED,
            anchor="mm",
        )
    return im


def frames(
    plan: list[Cut | Card],
    fps: int,
    captions: bool = True,
    crop: tuple | None = None,
    size: tuple[int, int] | None = None,
):
    """Yield output frames (PIL) for a plan at a constant frame rate."""
    scenes: dict[str, Scene] = {}
    prev: Image.Image | None = None
    fade_n = int(0.3 * fps)
    for item in plan:
        if isinstance(item, Card):
            im = card(item.kind)
            if crop:
                im = im.crop(crop)
            if size:
                im = im.resize(size, Image.LANCZOS)
            for _ in range(int(item.seconds * fps)):
                yield im
            prev = im
            continue
        sc = scenes.setdefault(item.scene, Scene(item.scene))
        t0 = sc.marks[item.mark] + item.start
        n = int(round((item.end - item.start) / item.speed * fps))
        width = (
            crop[2] - crop[0] if crop else UI_W
        )  # crop applies to the app, the caption follows it
        cap = strip(item.caption, item.note, width) if captions else None
        for k in range(n):
            ui = sc.at(t0 + k * item.speed / fps)
            if crop:
                ui = ui.crop(crop)
            if captions:
                im = Image.new("RGB", (ui.width, ui.height + STRIP))
                im.paste(ui, (0, 0))
                im.paste(cap, (0, ui.height))
            else:
                im = ui
            if size:
                im = im.resize(size, Image.LANCZOS)
            if item.fade and prev is not None and k < fade_n:
                im = Image.blend(prev, im, (k + 1) / (fade_n + 1))
            yield im
        prev = im


def encode_mp4(plan, path: Path, fps: int = 30, crf: int = 20, **kw) -> None:
    gen = frames(plan, fps, **kw)
    first = next(gen)
    w, h = first.size
    cmd = [
        FFMPEG,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{w}x{h}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    count = 1
    proc.stdin.write(first.tobytes())
    for im in gen:
        proc.stdin.write(im.tobytes())
        count += 1
    proc.stdin.close()
    assert proc.wait() == 0
    print(f"{path.name}: {count / fps:.1f} s, {w}x{h}, {path.stat().st_size / 1e6:.2f} MB")


def encode_gif(plan, path: Path, fps: int = 15, width: int = 960, **kw) -> None:
    tmp = OUT / (path.stem + "-src.mp4")
    if not tmp.exists() or "--fresh" in sys.argv:
        encode_mp4(plan, tmp, fps=fps, crf=12, **kw)
    # Ordered (Bayer) dithering keeps flat panels flat between frames, so the GIF compresses far
    # better than error diffusion, at the cost of a faint pattern in gradients.
    vf = (
        f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160:stats_mode=diff[p];"
        f"[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle"
    )
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-i", str(tmp), "-vf", vf, "-loop", "0", str(path)],
        check=True,
    )
    print(f"{path.name}: {path.stat().st_size / 1e6:.2f} MB")


# ---- the plans --------------------------------------------------------------------------------
G1 = "Unitree G1 model and policy: Unitree Robotics, BSD 3-Clause. Simulation."
DUCK = "Microduck model by Pollen Robotics, CC BY-NC-SA 4.0. Simulation."
G1_MJLAB = (
    "Unitree G1 model: Unitree Robotics, BSD 3-Clause. Policies trained with mjlab, Apache-2.0. "
    "Simulation."
)

FIRST_RUN = [
    Cut(
        "firstrun",
        "hero",
        0.0,
        4.4,
        "It opens on a real robot: Unitree's G1 humanoid, with its own trained walking policy.",
        G1,
    ),
    Cut(
        "firstrun",
        "license",
        0.0,
        5.9,
        "One click: read the license, agree, and it downloads the robot from its authors.",
    ),
    Cut(
        "firstrun",
        "accepted",
        0.4,
        31.3,
        "Then it shoves the robot 40 times, on the laptop's CPU.",
        "Download and check-up from an empty cache: 31 s, shown 8x faster.",
        speed=8.0,
    ),
    Cut(
        "firstrun",
        "results",
        0.3,
        3.8,
        "Done. It opens on a fall it found, with the reason beside it.",
        G1,
    ),
]
FALL = [
    Cut(
        "fall",
        "play",
        -0.4,
        3.6,
        "Watch it: a 150 N shove from the side, mid-stride, slowed down at the shove and the fall.",
        G1,
        fade=True,
    ),
    Cut(
        "fall",
        "play",
        3.6,
        8.6,
        "Why it fell, from the recorded run: its balance point went 63.6 cm outside its feet, "
        "and no step caught it.",
        G1,
    ),
]
WHAT_IF = [
    Cut(
        "whatif",
        "clicked",
        -1.2,
        1.4,
        "What if the shove were gentler? One click runs it again.",
        "This run took about 1 s.",
        fade=True,
    ),
    Cut(
        "whatif",
        "play",
        -0.3,
        7.2,
        "Both on one clock: at 100 N it leans 12 degrees and keeps walking. "
        "At 150 N it stays down.",
        G1,
    ),
]
POLICIES = [
    Cut("policies", "one", 0.0, 1.6, "The Microduck has two published policies.", DUCK, fade=True),
    Cut(
        "policies",
        "play",
        -0.3,
        9.2,
        "Same 3 N shove: the walk-only policy stays down; "
        "walk + get-up is back on its feet in 0.6 s.",
        DUCK,
    ),
]
OVERVIEW = [
    Cut(
        "overview",
        "top",
        0.6,
        3.8,
        "Every check-up: 40 shoves at five strengths and eight moments of the stride, "
        "plus floors and loads.",
        G1,
        fade=True,
    ),
]


def _g1pair_plan() -> list:
    """The two G1 policies on one shove, with the shove's own numbers in the caption."""
    info_file = HERE / "frames" / "g1pair" / "info.json"
    if not info_file.exists():
        return []
    info = json.loads(info_file.read_text())
    return [
        Cut(
            "g1pair",
            "one",
            0.0,
            1.6,
            "The 29-joint G1 has two walking policies: one trained with small shoves, "
            "one with strong ones.",
            G1_MJLAB,
            fade=True,
        ),
        Cut(
            "g1pair",
            "play",
            -0.3,
            9.2,
            f"Same {info['pushN']:g} N shove at the same moment: the small-shove policy falls at "
            f"{info['smallFellAt']:.1f} s, the strong-shove policy "
            + (
                "keeps walking."
                if info["strongOutcome"].startswith("Walked")
                else f"{info['strongOutcome'].lower()}."
            ),
            G1_MJLAB,
        ),
    ]


def _g1terrain_plan() -> list:
    """A toe caught on stairs, then a stone missed: each fall named by the panel. The captions
    quote the saved runs (info.json written by the recorder)."""
    stairs_file = HERE / "frames" / "g1stairs" / "info.json"
    stones_file = HERE / "frames" / "g1stones" / "info.json"
    if not stairs_file.exists() or not stones_file.exists():
        return []
    stairs = json.loads(stairs_file.read_text())
    stones = json.loads(stones_file.read_text())
    steps = stairs["title"].removeprefix("Stairs with ").lower()
    return [
        Cut(
            "g1stairs",
            "play",
            -0.3,
            4.2,
            f"Stairs with {steps}: a toe catches a step and it falls at {stairs['fellAt']:.1f} s. "
            "The panel names the step it caught.",
            G1_MJLAB,
            fade=True,
        ),
        Cut(
            "g1stones",
            "play",
            -0.2,
            4.6,
            f"{stones['title']}: a foot goes into a gap, and the panel says so.",
            G1_MJLAB,
            fade=True,
        ),
    ]


PLANS = {
    "pair_gif": _g1pair_plan(),
    "terrain_gif": _g1terrain_plan(),
    "tour": [
        Card("title", 2.6),
        *FIRST_RUN,
        *FALL,
        *WHAT_IF,
        *POLICIES,
        *OVERVIEW,
        Card("end", 4.5),
    ],
    "gif": [*FALL, *WHAT_IF],
}

if __name__ == "__main__":
    what = sys.argv[1]
    if what == "tour":
        encode_mp4(PLANS["tour"], OUT / "creature-lab-tour.mp4", fps=30, crf=21)
    elif what == "pair":
        # The README clip for the 29-joint G1: both policies, one shove.
        encode_gif(
            PLANS["pair_gif"],
            OUT / "creature-lab-g1-policies.gif",
            fps=int(sys.argv[2]) if len(sys.argv) > 2 else 10,
            width=int(sys.argv[3]) if len(sys.argv) > 3 else 800,
            crop=(452, 0, UI_W, UI_H),
        )
    elif what == "terrain":
        # The README clip for uneven ground: stairs side by side, then a missed stepping stone.
        encode_gif(
            PLANS["terrain_gif"],
            OUT / "creature-lab-terrain.gif",
            fps=int(sys.argv[2]) if len(sys.argv) > 2 else 10,
            width=int(sys.argv[3]) if len(sys.argv) > 3 else 800,
            crop=(452, 0, UI_W, UI_H),
        )
    elif what == "site_terrain":
        # The portfolio card: a shove, stairs and stepping stones, no captions (the card has words).
        plan = [
            Cut("g1pair", "play", 0.2, 6.2),
            Cut("g1stairs", "play", -0.2, 4.4, fade=True),
            Cut("g1stones", "play", 0.0, 4.4, fade=True),
        ]
        encode_mp4(
            plan,
            OUT / "creature-lab-demo.mp4",
            fps=30,
            crf=28,
            captions=False,
            crop=(480, 127, 1366, 681),
            size=(960, 600),
        )
    elif what == "gif":
        # The README GIF leaves out the robot list on the left: the robot and the words are bigger.
        encode_gif(
            PLANS["gif"],
            OUT / "creature-lab-demo.gif",
            fps=int(sys.argv[2]) if len(sys.argv) > 2 else 12,
            width=int(sys.argv[3]) if len(sys.argv) > 3 else 880,
            crop=(452, 0, UI_W, UI_H),
        )
    elif what == "site":
        # The portfolio card is 16:10 and has its own words: no captions, the stage and the panel.
        plan = [
            Cut("fall", "play", 0.4, 7.0),
            Cut("whatif", "play", -0.2, 6.8, fade=True),
        ]
        crop = (480, 127, 1366, 681)  # the 3D view and the playback bar
        encode_mp4(
            plan,
            OUT / "creature-lab-demo.mp4",
            fps=30,
            crf=27,
            captions=False,
            crop=crop,
            size=(960, 600),
        )
    elif what == "poster":
        sc = Scene("whatif")
        im = (
            sc.at(sc.marks["play"] + 2.2)
            .crop((480, 127, 1366, 681))
            .resize((960, 600), Image.LANCZOS)
        )
        im.save(OUT / "creature-lab-poster.webp", quality=82)
        print("poster", (OUT / "creature-lab-poster.webp").stat().st_size)
    elif what == "still":
        # One frame of each cut with its caption, for checking the words and the layout.
        name = sys.argv[2]
        for k, item in enumerate(PLANS[name]):
            gen = frames([item], 30)
            for _ in range(int(0.6 * 30)):
                im = next(gen)
            im.resize((960, 540)).save(OUT / f"still-{name}-{k:02d}.png")
        print("stills written")
