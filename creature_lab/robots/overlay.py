"""2D graphics for check-up media: HUD, timeline, cards and charts (Pillow, supersampled)."""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from creature_lab.robots.analysis import FALL_UPRIGHT
from creature_lab.robots.types import RobotRun

BG = (11, 16, 28)
PANEL = (17, 25, 42)
TEXT = (240, 244, 250)
MUTED = (148, 163, 190)
ORANGE = (255, 122, 48)
TEAL = (38, 190, 164)
RED = (240, 82, 76)
AMBER = (252, 204, 60)
GRID = (44, 58, 86)

_SS = 2  # supersampling factor for smooth edges

_FONT_FILES = {
    "regular": ("segoeui.ttf", "SFNS.ttf", "Helvetica.ttc", "DejaVuSans.ttf", "Arial.ttf"),
    "bold": ("segoeuib.ttf", "SFNS.ttf", "Helvetica.ttc", "DejaVuSans-Bold.ttf", "Arialbd.ttf"),
}
_FONT_DIRS = (
    Path("C:/Windows/Fonts"),
    Path("/System/Library/Fonts"),
    Path("/Library/Fonts"),
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/dejavu"),
)

#: A small RGBA tile at 1x resolution plus where it goes in the frame.
Sprite = tuple[Image.Image, int, int]


@lru_cache(maxsize=64)
def font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """A system font at ``size`` px, falling back to Pillow's bundled one."""
    for name in _FONT_FILES[weight]:
        for folder in _FONT_DIRS:
            path = folder / name
            if path.is_file():
                try:
                    return ImageFont.truetype(str(path), size)
                except OSError:
                    continue
    return ImageFont.load_default(size)


def canvas(width: int, height: int, fill=BG) -> Image.Image:
    return Image.new("RGB", (width, height), fill)


def layer(width: int, height: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGBA", (width * _SS, height * _SS), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image)


def composite(base: Image.Image, overlay: Image.Image) -> Image.Image:
    """Smoothly lay a full-frame supersampled RGBA overlay over ``base``."""
    small = overlay.resize(base.size, Image.LANCZOS)
    out = base.convert("RGBA")
    out.alpha_composite(small)
    return out.convert("RGB")


def sprite(x: float, y: float, width: float, height: float, paint) -> Sprite:
    """Paint a small supersampled tile in local coordinates; returns (image, x, y)."""
    w, h = int(np.ceil(width)), int(np.ceil(height))
    tile = Image.new("RGBA", (w * _SS, h * _SS), (0, 0, 0, 0))
    paint(ImageDraw.Draw(tile))
    return tile.resize((w, h), Image.LANCZOS), int(x), int(y)


def paste(base: Image.Image, sprites: Sequence[Sprite]) -> Image.Image:
    """Lay sprites over ``base`` (each clipped to the frame)."""
    out = base.convert("RGBA")
    for tile, x, y in sprites:
        crop_x, crop_y = max(-x, 0), max(-y, 0)
        if crop_x or crop_y:
            tile = tile.crop((crop_x, crop_y, tile.width, tile.height))
        out.alpha_composite(tile, (max(x, 0), max(y, 0)))
    return out.convert("RGB")


def _s(value):
    if isinstance(value, (tuple, list)):
        return tuple(int(v * _SS) for v in value)
    return int(value * _SS)


def text(draw, xy, content, size, fill=TEXT, weight="regular", anchor="la", alpha=255):
    draw.text(_s(xy), content, font=font(size * _SS, weight), fill=(*fill, alpha), anchor=anchor)


def text_width(content: str, size: int, weight: str = "regular") -> float:
    return font(size * _SS, weight).getlength(content) / _SS


def wrap(content: str, size: int, width: float, weight: str = "regular") -> list[str]:
    lines, line = [], ""
    for word in content.split():
        trial = f"{line} {word}".strip()
        if text_width(trial, size, weight) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def panel(draw, box, radius=18, fill=PANEL, alpha=215, outline=None):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(
        _s((x0, y0, x1, y1)),
        radius=_s(radius),
        fill=(*fill, alpha),
        outline=None if outline is None else (*outline, 255),
        width=_s(2),
    )


def pill(draw, xy, content, size=22, fill=ORANGE, color=(255, 255, 255), pad=(16, 8)):
    width = text_width(content, size, "bold") + 2 * pad[0]
    height = size * 1.25 + 2 * pad[1]
    x, y = xy
    draw.rounded_rectangle(
        _s((x, y, x + width, y + height)), radius=_s(height / 2), fill=(*fill, 255)
    )
    text(draw, (x + pad[0], y + pad[1] + size * 0.05), content, size, color, "bold")
    return width, height


def title_card(
    width: int, height: int, title: str, subtitle: str = "", kicker: str = ""
) -> Image.Image:
    """A dark gradient card with a big headline."""
    gradient = np.linspace(0, 1, height)[:, None, None]
    top, bottom = np.array([14, 21, 38]), np.array([8, 12, 22])
    base = Image.fromarray((top + (bottom - top) * gradient).repeat(width, axis=1).astype("uint8"))
    over, draw = layer(width, height)
    left = width * 0.08
    if kicker:
        text(draw, (left, height * 0.30), kicker.upper(), 30, ORANGE, "bold")
    y = height * 0.38
    for line in wrap(title, 84, width * 0.82, "bold"):
        text(draw, (left, y), line, 84, TEXT, "bold")
        y += 100
    draw.rectangle(_s((left, y + 14, left + 120, y + 20)), fill=(*ORANGE, 255))
    if subtitle:
        y += 48
        for line in wrap(subtitle, 36, width * 0.7):
            text(draw, (left, y), line, 36, MUTED)
            y += 48
    return composite(base, over)


def tilt_timeline(run: RobotRun, box: tuple[int, int, int, int], now_s: float) -> Sprite:
    """Lean-angle history with a playhead, the shove and the 60° fall line."""
    x0, y0, x1, y1 = box
    width, height = (x1 - x0) + 32, (y1 - y0) + 46
    tilt = np.degrees(np.arccos(np.clip(run.upright, -1, 1)))
    duration = float(run.time[-1])
    plot_h = y1 - y0

    def paint(draw):
        def px(t):
            return 16 + (x1 - x0) * t / duration

        def py(deg):
            return 34 + plot_h - plot_h * min(deg, 100) / 100

        panel(draw, (0, 0, width, height), 14, alpha=190)
        text(draw, (16, 6), "LEAN ANGLE", 15, MUTED, "bold")
        fall_y = py(np.degrees(np.arccos(FALL_UPRIGHT)))
        draw.line(_s((16, fall_y, width - 16, fall_y)), fill=(*RED, 150), width=_s(1.5))
        text(draw, (width - 20, fall_y - 4), "fall (60°)", 14, RED, anchor="rd")
        scenario = run.scenario
        if scenario.push_n > 0:
            sx = px(scenario.push_at_s)
            draw.rectangle(
                _s((sx, 34, px(scenario.push_at_s + scenario.push_for_s) + 2, 34 + plot_h)),
                fill=(*ORANGE, 130),
            )
            text(draw, (sx + 6, 36), "shove", 14, ORANGE, "bold")
        shown = run.time <= now_s
        if shown.sum() > 1:
            points = [(px(t), py(d)) for t, d in zip(run.time[shown], tilt[shown], strict=True)]
            draw.line([_s(p) for p in points], fill=(*TEAL, 255), width=_s(3), joint="curve")
            cx, cy = points[-1]
            draw.ellipse(_s((cx - 6, cy - 6, cx + 6, cy + 6)), fill=(*TEXT, 255))

    return sprite(x0 - 16, y0 - 34, width, height, paint)


def hud(
    size: tuple[int, int],
    *,
    robot: str,
    policy: str,
    tag: str | None,
    tag_color=ORANGE,
    now_s: float,
    credit: str,
    slow: float = 1.0,
    show_clock: bool = True,
) -> list[Sprite]:
    """Top-left: what you are watching. Top-right: the current event. Bottom-left: credit."""
    width, height = size
    chip_w = text_width(robot.upper(), 24, "bold") + text_width(policy, 22) + 74

    def chip(draw):
        panel(draw, (0, 0, chip_w, 56), 14)
        text(draw, (18, 14), robot.upper(), 24, ORANGE, "bold")
        text(draw, (18 + text_width(robot.upper(), 24, "bold") + 20, 16), policy, 22, TEXT)

    sprites = [sprite(28, 26, chip_w, 56, chip)]
    if tag:
        tag_w = text_width(tag, 22, "bold") + 32
        # In a narrow frame the tag would collide with the chip, so it drops below it.
        crowded = 28 + chip_w + 16 + tag_w > width - 28
        tag_x, tag_y = (28, 92) if crowded else (width - 28 - tag_w, 30)
        sprites.append(
            sprite(tag_x, tag_y, tag_w, 48, lambda d: pill(d, (0, 0), tag, 22, tag_color))
        )
    if show_clock:
        clock = f"t = {now_s:4.1f} s" + (f"   {slow:g}× slow motion" if slow < 0.99 else "")
        clock_w = text_width(clock, 20) + 8
        sprites.append(
            sprite(
                width - 32 - clock_w,
                92,
                clock_w,
                30,
                lambda d: text(d, (clock_w - 4, 4), clock, 20, MUTED, anchor="ra"),
            )
        )
    credit_w = text_width(credit, 15) + 8
    sprites.append(
        sprite(30, height - 42, credit_w, 24, lambda d: text(d, (0, 2), credit, 15, MUTED))
    )
    return sprites


def caption(size: tuple[int, int], lines: Sequence[str], *, y_from_bottom=210) -> Sprite:
    width, height = size
    line_h = 46
    box_h = line_h * len(lines) + 30
    box_w = max(text_width(line, 34, "bold") for line in lines) + 64

    def paint(draw):
        panel(draw, (0, 0, box_w, box_h), 18, alpha=220)
        for index, line in enumerate(lines):
            text(draw, (box_w / 2, 16 + index * line_h), line, 34, TEXT, "bold", "ma")

    return sprite((width - box_w) / 2, height - y_from_bottom - box_h, box_w, box_h, paint)


def evidence_panel(heading: str, items: Sequence[tuple[str, str, tuple]], shown: float) -> Sprite:
    """Left-hand card listing evidence rows; ``shown`` (0..len) reveals them one by one."""
    row = 112
    box_w, box_h = 590, 74 + row * len(items)

    def paint(draw):
        panel(draw, (0, 0, box_w, box_h), 20, alpha=225)
        text(draw, (28, 22), heading.upper(), 22, ORANGE, "bold")
        for index, (label, value, color) in enumerate(items):
            alpha = int(255 * min(max(shown - index, 0.0), 1.0))
            if alpha == 0:
                continue
            y = 74 + index * row
            draw.rounded_rectangle(
                _s((28, y + 6, 36, y + row - 18)), radius=_s(4), fill=(*color, alpha)
            )
            text(draw, (56, y), label, 22, MUTED, alpha=alpha)
            text(draw, (56, y + 30), value, 36, TEXT, "bold", alpha=alpha)

    return sprite(36, 150, box_w, box_h, paint)


def hero_shade(base: Image.Image) -> Image.Image:
    """Darken the left of the frame so the headline reads over the shot."""
    array = np.asarray(base.convert("RGB")).astype(np.float32)
    ramp = np.clip(1.0 - np.arange(base.width) / (base.width * 0.62), 0, 1) ** 1.4 * 0.84
    shade = ramp[None, :, None]
    blended = array * (1 - shade) + np.array(BG, dtype=np.float32) * shade
    return Image.fromarray(blended.astype(np.uint8))


def hero_text(size: tuple[int, int], kicker: str, title: str, subtitle: str) -> Sprite:
    width, height = size
    lines = wrap(title, 76, width * 0.48, "bold")
    sub = wrap(subtitle, 32, width * 0.42)
    box_h = 70 + 90 * len(lines) + 46 * len(sub) + 110

    def paint(draw):
        text(draw, (0, 0), kicker.upper(), 28, ORANGE, "bold")
        y = 56.0
        for line in lines:
            text(draw, (0, y), line, 76, TEXT, "bold")
            y += 90
        draw.rectangle(_s((0, y + 10, 110, y + 16)), fill=(*ORANGE, 255))
        for line in sub:
            y += 46
            text(draw, (0, y + 28), line, 32, MUTED)

    return sprite(width * 0.06, height * 0.27, width * 0.5, box_h, paint)


def bar_chart(
    size: tuple[int, int],
    title: str,
    subtitle: str,
    groups: Sequence[str],
    series: Sequence[tuple[str, tuple, Sequence[float]]],
    top: float,
    reveal: float,
    unit: str = "",
    footer: Sequence[str] = (),
) -> Image.Image:
    """Grouped bars growing in over ``reveal`` (0..1)."""
    width, height = size
    base = canvas(width, height, BG)
    over, draw = layer(width, height)
    text(draw, (96, 70), title, 52, TEXT, "bold")
    text(draw, (96, 140), subtitle, 28, MUTED)
    x0, x1, y0, y1 = 150, width - 110, 270, height - 190
    for tick in range(0, int(top) + 1, max(1, int(top) // 4)):
        y = y1 - (y1 - y0) * tick / top
        draw.line(_s((x0, y, x1, y)), fill=(*GRID, 255), width=_s(1.5))
        text(draw, (x0 - 14, y), f"{tick}", 22, MUTED, anchor="rm")
    group_w = (x1 - x0) / len(groups)
    bar_w = min(70, group_w / (len(series) + 1.2))
    for g, label in enumerate(groups):
        gx = x0 + group_w * (g + 0.5)
        text(draw, (gx, y1 + 22), label, 26, TEXT, "bold", "ma")
        for s, (_, color, values) in enumerate(series):
            value = values[g] * min(max(reveal * 1.4 - 0.05 * g, 0.0), 1.0)
            left = gx + (s - (len(series) - 1) / 2) * (bar_w + 10) - bar_w / 2
            top_y = y1 - (y1 - y0) * value / top
            if value > 0:
                draw.rounded_rectangle(
                    _s((left, top_y, left + bar_w, y1)), radius=_s(8), fill=(*color, 255)
                )
            if reveal > 0.85:
                text(
                    draw,
                    (left + bar_w / 2, top_y - 10),
                    f"{values[g]:g}{unit}",
                    24,
                    TEXT,
                    "bold",
                    "md",
                )
    for index, line in enumerate(footer):
        text(
            draw,
            (96, height - 112 + index * 40),
            line,
            28,
            TEXT if index == 0 else MUTED,
            "bold" if index == 0 else "regular",
        )
    legend_x = x1
    for name, color, _ in reversed(series):
        legend_x -= text_width(name, 24) + 54
        draw.rounded_rectangle(
            _s((legend_x, 94, legend_x + 26, 120)), radius=_s(6), fill=(*color, 255)
        )
        text(draw, (legend_x + 38, 92), name, 24, TEXT)
    return composite(base, over)


def to_array(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGB"))
