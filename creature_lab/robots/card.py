"""A robustness card: one picture and one sentence that say how a policy handles shoves.

Made for a README or a model card. It is built from a saved ``checkup.json`` only, so it needs no
simulator. The card says what was simulated and credits the model, like the report does.
"""

from __future__ import annotations

import html
from pathlib import Path

from creature_lab import VERSION
from creature_lab.robots.catalog import robot_info
from creature_lab.robots.checkup import Checkup, ShoveRow
from creature_lab.robots.report import limit_text

_UP, _GOT, _DOWN = "#1aa38b", "#f2b705", "#e5484d"
_INK, _MUTED, _PAPER, _LINE = "#101828", "#5b667a", "#ffffff", "#e3e7ef"
_FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
_CELL, _GAP = 14, 4


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if len(candidate) > width and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def _limit_phrase(limit: float | None, checkup: Checkup, event: str) -> str:
    """'never fell up to 2 N', 'never fell in any test (up to 8 N)', 'fell even at 1 N'."""
    tested = checkup.shoves[-1].force_n
    if limit is None:
        return f"{event} even at {checkup.shoves[0].force_n:g} N"
    if limit == tested:
        return f"never {event} in any test (up to {tested:g} N)"
    return f"never {event} up to {limit:g} N"


def claim(checkup: Checkup) -> str:
    """One sentence for a README or model card."""
    info = robot_info(checkup.robot)
    policy = info.policy(checkup.policy).title
    total = sum(row.total for row in checkup.shoves)
    up = sum(row.stayed_up for row in checkup.shoves)
    on_floor = sum(row.stayed_down for row in checkup.shoves)
    fell = _limit_phrase(checkup.never_falls_up_to_n, checkup, "fell")
    stayed_down = _limit_phrase(checkup.never_stays_down_up_to_n, checkup, "stayed on the floor")
    return (
        f"{info.title}, {policy}: {fell}; {stayed_down}. {up} of {total} simulated shoves ended "
        f"standing and {on_floor} left it on the floor (Creature Lab {VERSION}, simulation)."
    )


def markdown(checkup: Checkup, card_path: str | None = None) -> str:
    """The claim plus, when the card is committed next to it, the picture."""
    lines = [f"**Robustness** (simulated with Creature Lab): {claim(checkup)}"]
    if card_path:
        lines += ["", f"![Robustness card for {checkup.robot} / {checkup.policy}]({card_path})"]
    return "\n".join(lines) + "\n"


def _strip(row: ShoveRow, x: int, y: int) -> str:
    cells = ["up"] * row.stayed_up + ["got"] * row.got_up + ["down"] * row.stayed_down
    colour = {"up": _UP, "got": _GOT, "down": _DOWN}
    out = [
        f'<rect x="{x + i * (_CELL + _GAP)}" y="{y}" width="{_CELL}" height="{_CELL}" rx="3" '
        f'fill="{colour[kind]}"/>'
        for i, kind in enumerate(cells)
    ]
    return "".join(out)


def card_svg(checkup: Checkup) -> str:
    """The robustness card as a standalone SVG (renders in a README or a browser)."""
    info = robot_info(checkup.robot)
    policy = info.policy(checkup.policy)
    width = 760
    rows = checkup.shoves
    conditions = checkup.conditions
    row_h = 30
    top = 168
    strip_end = top + len(rows) * row_h
    chip_lines = 0
    chips: list[str] = []
    x = 36
    y = strip_end + 56
    for result in conditions:
        mark = "stayed up" if result.passed else "fell"
        text = f"{result.label} · {mark}"
        text_w = round(7.6 * len(text)) + 26  # a generous estimate: fonts differ per viewer
        if x + text_w > width - 36:
            x = 36
            y += 32
            chip_lines += 1
        fill = "#e6f6f2" if result.passed else "#fdebec"
        ink = "#0e7a67" if result.passed else "#b4232a"
        chips.append(
            f'<rect x="{x}" y="{y - 18}" width="{text_w}" height="26" rx="13" fill="{fill}"/>'
            f'<text x="{x + 13}" y="{y}" font-size="13" fill="{ink}" font-weight="600">'
            f"{_e(text)}</text>"
        )
        x += text_w + 10
    chip_block = "".join(chips)
    footer_y = (y + 44) if conditions else (strip_end + 36)
    height = footer_y + 52

    never_falls = limit_text(checkup.never_falls_up_to_n, checkup)
    never_down = limit_text(checkup.never_stays_down_up_to_n, checkup)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Robustness card: {_e(info.title)}, {_e(policy.title)}">',
        f"<title>{_e(info.title)} · {_e(policy.title)}: robustness card</title>",
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="18" fill="{_PAPER}" '
        f'stroke="{_LINE}"/>',
        f'<g font-family="{_FONT}">',
        '<text x="36" y="48" font-size="13" font-weight="700" fill="#f26a1b" '
        'letter-spacing="1.4">ROBUSTNESS CARD</text>',
        f'<text x="36" y="84" font-size="28" font-weight="800" fill="{_INK}">'
        f"{_e(info.title)} · {_e(policy.title)}</text>",
        f'<text x="36" y="118" font-size="16" fill="{_MUTED}">Shoved at {len(rows)} strengths, '
        f"{rows[0].total} moments of the stride each, in simulation.</text>",
        f'<text x="36" y="150" font-size="17" fill="{_INK}"><tspan font-weight="700">Stays on its '
        f"feet:</tspan> {_e(never_falls)}   "
        f'<tspan font-weight="700">Never left on the floor:</tspan> {_e(never_down)}</text>',
    ]
    for i, row in enumerate(rows):
        yy = top + i * row_h
        parts.append(
            f'<text x="36" y="{yy + 13}" font-size="15" font-weight="600" fill="{_INK}">'
            f"{row.force_n:g} N</text>"
        )
        parts.append(_strip(row, 110, yy))
        detail = f"{row.stayed_up} up · {row.got_up} got up · {row.stayed_down} stayed down"
        parts.append(
            f'<text x="{110 + row.total * (_CELL + _GAP) + 12}" y="{yy + 13}" font-size="13" '
            f'fill="{_MUTED}">{_e(detail)}</text>'
        )
    legend_y = strip_end + 14
    parts.append(
        f'<g font-size="12" fill="{_MUTED}">'
        f'<rect x="36" y="{legend_y - 10}" width="12" height="12" rx="3" fill="{_UP}"/>'
        f'<text x="54" y="{legend_y}">stayed up</text>'
        f'<rect x="130" y="{legend_y - 10}" width="12" height="12" rx="3" fill="{_GOT}"/>'
        f'<text x="148" y="{legend_y}">fell, got up</text>'
        f'<rect x="240" y="{legend_y - 10}" width="12" height="12" rx="3" fill="{_DOWN}"/>'
        f'<text x="258" y="{legend_y}">stayed down</text></g>'
    )
    parts.append(chip_block)
    for i, line in enumerate(
        _wrap(
            f"{info.credit}. A simulation of the published model, not "
            f"the hardware. Made with Creature Lab {VERSION}.",
            104,
        )
    ):
        parts.append(
            f'<text x="36" y="{footer_y + i * 18}" font-size="12" fill="{_MUTED}">{_e(line)}</text>'
        )
    parts.append("</g></svg>")
    return "".join(parts)


def write_card(checkup: Checkup, destination: Path) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(card_svg(checkup), encoding="utf-8")
    return destination
