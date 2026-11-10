"""Compare two check-ups of the same robot: did a change make it more or less robust?

This reads saved ``checkup.json`` files only (no simulator), so it runs anywhere, including a CI
job that has just trained a new policy and wants to know whether it regressed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from creature_lab.robots.checkup import Checkup, ConditionResult, ShoveRow, read_checkup
from creature_lab.schema.base import StrictModel

Verdict = Literal["better", "worse", "same"]


class CompareError(ValueError):
    """The folders cannot be compared (missing results, different robots)."""


class Change(StrictModel):
    """One test, before and after."""

    kind: Literal["baseline", "shove", "condition"]
    label: str
    before: str
    after: str
    verdict: Verdict


class Comparison(StrictModel):
    schema_id: str = "creature-lab.robot-compare/1"
    robot: str
    before_policy: str
    after_policy: str
    changes: list[Change]
    #: Strengths (or conditions) only one side tested; they are not compared.
    skipped: list[str]

    @property
    def regressions(self) -> list[Change]:
        return [c for c in self.changes if c.verdict == "worse"]

    @property
    def improvements(self) -> list[Change]:
        return [c for c in self.changes if c.verdict == "better"]

    @property
    def regressed(self) -> bool:
        return bool(self.regressions)

    def summary(self) -> str:
        worse, better = len(self.regressions), len(self.improvements)
        same = len(self.changes) - worse - better
        if worse and better:
            head = f"Mixed: {worse} test(s) got worse, {better} got better"
        elif worse:
            head = f"Regressed: {worse} test(s) got worse"
        elif better:
            head = f"Improved: {better} test(s) got better, none got worse"
        else:
            head = "No change"
        return f"{head} ({same} unchanged of {len(self.changes)} compared)."

    def to_markdown(self) -> str:
        """A short table for a pull-request comment or a model card."""
        lines = [
            f"**{self.robot.replace('_', ' ')}: `{self.before_policy}` → `{self.after_policy}`**",
            "",
            self.summary(),
            "",
            "| Test | Before | After | |",
            "| --- | --- | --- | --- |",
        ]
        mark = {"better": "better", "worse": "**worse**", "same": ""}
        for change in self.changes:
            if change.verdict == "same":
                continue
            lines.append(
                f"| {change.label} | {change.before} | {change.after} | {mark[change.verdict]} |"
            )
        if not (self.regressions or self.improvements):
            lines.append("| _nothing differs_ | | | |")
        if self.skipped:
            lines += ["", "Not compared (only one side ran them): " + ", ".join(self.skipped)]
        return "\n".join(lines) + "\n"


def find_checkup(path: Path, policy: str | None = None) -> Path:
    """The folder holding ``checkup.json``: ``path`` itself, or one policy folder under it."""
    path = Path(path)
    if (path / "checkup.json").is_file():
        return path
    found = {read_checkup(f.parent).policy: f.parent for f in path.glob("*/checkup.json")}
    if not found:
        raise CompareError(f"no check-up results in {path} (expected checkup.json)")
    if policy is not None:
        if policy not in found:
            raise CompareError(f"{path} has no policy {policy!r} (found: {', '.join(found)})")
        return found[policy]
    if len(found) > 1:
        raise CompareError(
            f"{path} holds several policies ({', '.join(found)}); pick one with --policy"
        )
    return next(iter(found.values()))


def _row_cost(row: ShoveRow) -> int:
    """Staying down counts double a fall that gets back up; staying up costs nothing."""
    return row.stayed_down * 2 + row.got_up


def _row_text(row: ShoveRow) -> str:
    return f"{row.stayed_up} up, {row.got_up} got up, {row.stayed_down} stayed down"


def _condition_text(result: ConditionResult) -> str:
    return "passed" if result.passed else "fell"


def compare_checkups(before: Checkup, after: Checkup, *, tolerance: int = 0) -> Comparison:
    """Compare two check-ups of one robot.

    A shove strength gets worse when its cost rises by more than ``tolerance`` (a shove that leaves
    the robot on the floor costs 2, one it recovers from costs 1). A grip, battery or payload test
    gets worse when it passed before and falls now.
    """
    if before.robot != after.robot:
        raise CompareError(f"different robots: {before.robot} and {after.robot}")
    changes: list[Change] = []
    skipped: list[str] = []

    base_before = "fell" if before.baseline.fell else "walked"
    base_after = "fell" if after.baseline.fell else "walked"
    changes.append(
        Change(
            kind="baseline",
            label="Baseline walk",
            before=base_before,
            after=base_after,
            verdict=(
                "worse"
                if after.baseline.fell and not before.baseline.fell
                else "better"
                if before.baseline.fell and not after.baseline.fell
                else "same"
            ),
        )
    )

    before_rows = {row.force_n: row for row in before.shoves}
    after_rows = {row.force_n: row for row in after.shoves}
    for force in sorted(before_rows.keys() | after_rows.keys()):
        old, new = before_rows.get(force), after_rows.get(force)
        if old is None or new is None:
            skipped.append(f"{force:g} N shove")
            continue
        if old.total != new.total:
            skipped.append(f"{force:g} N shove (different shove counts)")
            continue
        delta = _row_cost(new) - _row_cost(old)
        verdict: Verdict = "worse" if delta > tolerance else "better" if delta < 0 else "same"
        changes.append(
            Change(
                kind="shove",
                label=f"{force:g} N shove",
                before=_row_text(old),
                after=_row_text(new),
                verdict=verdict,
            )
        )

    before_conditions = {c.key: c for c in before.conditions}
    after_conditions = {c.key: c for c in after.conditions}
    for key in before_conditions.keys() | after_conditions.keys():
        old_c, new_c = before_conditions.get(key), after_conditions.get(key)
        if old_c is None or new_c is None:
            skipped.append((old_c or new_c).label)  # type: ignore[union-attr]
            continue
        changes.append(
            Change(
                kind="condition",
                label=new_c.label,
                before=_condition_text(old_c),
                after=_condition_text(new_c),
                verdict=(
                    "worse"
                    if old_c.passed and not new_c.passed
                    else "better"
                    if new_c.passed and not old_c.passed
                    else "same"
                ),
            )
        )

    return Comparison(
        robot=before.robot,
        before_policy=before.policy,
        after_policy=after.policy,
        changes=changes,
        skipped=sorted(skipped),
    )


def compare_folders(
    before: Path,
    after: Path,
    *,
    policy: str | None = None,
    before_policy: str | None = None,
    after_policy: str | None = None,
    tolerance: int = 0,
) -> Comparison:
    """Read two result folders and compare them (see ``find_checkup`` for the folder rules)."""
    left = read_checkup(find_checkup(before, before_policy or policy))
    right = read_checkup(find_checkup(after, after_policy or policy))
    return compare_checkups(left, right, tolerance=tolerance)


def write_json(comparison: Comparison, destination: Path) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(comparison.model_dump_json())
    payload["regressed"] = comparison.regressed
    payload["summary"] = comparison.summary()
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return destination
