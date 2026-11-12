"""The check-ups and runs on this machine, as the browser app lists them.

Everything comes from folders ``creature-lab robots checkup`` wrote. The browser only ever sees
opaque run ids; it never supplies a path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from creature_lab.robots.analysis import RunAnalysis, analyze
from creature_lab.robots.catalog import all_robots, robot_info
from creature_lab.robots.checkup import TWIN_FIELDS, Checkup
from creature_lab.robots.types import RobotRun

#: Run folders in the order they are listed: the walk, shoves, then bad conditions.
_ORDER = ("baseline", "shove", "terrain", "damage", "grip", "battery", "payload", "whatif")


def _run_id(folder: Path) -> str:
    return hashlib.sha1(str(folder.resolve()).encode("utf-8")).hexdigest()[:12]


@dataclass
class RunEntry:
    """One saved run, summarised for a card."""

    id: str
    robot: str
    policy: str
    folder: Path
    name: str
    title: str
    kind: str
    analysis: RunAnalysis
    scenario: dict
    mtime: float
    #: The same test run with another of the robot's policies (same shove, floor, battery, load),
    #: the one whose outcome differs most. For a "what if" run it is the run it was made from, so
    #: the two can be shown together.
    pair: str | None = None
    #: The same test under every other policy, in the robot's policy order.
    pairs: list[str] = field(default_factory=list)
    #: For a "what if" run: what was changed (``label``, ``short``, ``change``, ``from``).
    what_if: dict | None = None

    def card(self) -> dict:
        info = robot_info(self.robot)
        a = self.analysis
        return {
            "id": self.id,
            "robot": self.robot,
            "policy": self.policy,
            "policyTitle": info.policy(self.policy).title,
            "title": self.title,
            "kind": self.kind,
            "outcome": a.outcome,
            "stalled": a.stalled,
            "outcomeText": _outcome_text(a),
            "verdict": a.verdict,
            "fallAt": a.fall_time_s,
            "recoveredAt": a.recovered_time_s,
            "distance": round(a.distance_m, 2),
            "pushN": self.scenario.get("push_n", 0.0),
            "pair": self.pair,
            "pairs": self.pairs,
            "whatIf": self.what_if["label"] if self.what_if else None,
            "whatIfShort": self.what_if["short"] if self.what_if else None,
        }


def _not_stuck_when_standing_is_normal(entries: list[RunEntry]) -> None:
    """A policy whose own baseline goes nowhere (a stand-still policy) is never "stuck": going
    nowhere is what it does. Its runs keep their sentences, without the stuck mark."""
    standing = {e.policy for e in entries if e.kind == "baseline" and e.analysis.stalled}
    for entry in entries:
        if entry.policy in standing and entry.analysis.stalled:
            entry.analysis = entry.analysis.model_copy(update={"stalled": False})


def _condition_row(condition, entry, run: str | None) -> dict:
    """One "floors, batteries and loads" row, judged by the same analysis as its run's own view.

    The pass recorded in checkup.json is from when the check-up ran. The run itself is analysed
    afresh when the library loads, so a check-up saved before a rule changed (staying up while
    stuck at the foot of a ramp used to pass) would show "Stopped at 0.7 m" on the run and "Pass"
    in this list.
    """
    analysis = entry.analysis if entry is not None else condition.analysis
    return {
        "label": condition.label,
        "passed": not analysis.fell and not analysis.stalled,
        "stalled": analysis.stalled,
        "relativeDistance": round(condition.relative_distance, 2),
        "verdict": analysis.verdict,
        "run": run,
    }


def _outcome_text(analysis: RunAnalysis) -> str:
    if analysis.outcome == "walked":
        # A shove can leave it standing but going nowhere or backwards: "Walked -0.2 m" misleads.
        if analysis.distance_m < 0.25:
            return "Stayed up, barely moved"
        if analysis.stalled:
            return f"Stopped at {analysis.distance_m:.1f} m"
        return f"Walked {analysis.distance_m:.1f} m"
    if analysis.outcome == "fell_and_got_up" and analysis.recovered_time_s is not None:
        return f"Back up in {analysis.recovered_time_s - (analysis.fall_time_s or 0):.1f} s"
    return "Stayed down"


def _kind(name: str) -> str:
    for word in _ORDER:
        if name.startswith(word):
            return word
    return "other"


def _pair_key(entry: RunEntry) -> tuple:
    # Terrain is a dict; its JSON text makes it comparable and hashable.
    return (
        entry.kind,
        *(json.dumps(entry.scenario.get(field), sort_keys=True) for field in TWIN_FIELDS),
    )


def _link_pairs(entries: list[RunEntry]) -> None:
    """Point each run at its twin under the other policy, so the app can show them together.

    A "what if" run points at the run it was made from instead.
    """
    groups: dict[tuple, list[RunEntry]] = {}
    for entry in entries:
        if entry.what_if is None:
            groups.setdefault(_pair_key(entry), []).append(entry)
    by_folder = {(entry.policy, entry.folder.name): entry for entry in entries}
    for entry in entries:
        if entry.what_if is not None:
            source = by_folder.get((entry.policy, str(entry.what_if.get("from"))))
            entry.pair = source.id if source else None
            continue
        twins = _one_per_policy(e for e in groups[_pair_key(entry)] if e.policy != entry.policy)
        entry.pairs = [twin.id for twin in twins]
        # The comparison worth opening first: the twin whose outcome differs most (a fall beside a
        # walk), else the first policy.
        entry.pair = (
            max(twins, key=lambda t: abs(_severity(t) - _severity(entry))).id if twins else None
        )


def _one_per_policy(twins) -> list[RunEntry]:
    """The first run of each policy (entries arrive sorted), in the robot's policy order."""
    chosen: dict[str, RunEntry] = {}
    for twin in twins:
        chosen.setdefault(twin.policy, twin)
    if not chosen:
        return []
    order = [p.key for p in robot_info(next(iter(chosen.values())).robot).policies]
    return sorted(chosen.values(), key=lambda t: order.index(t.policy) if t.policy in order else 99)


def _severity(entry: RunEntry) -> int:
    return {"walked": 0, "fell_and_got_up": 1}.get(entry.analysis.outcome, 2)


def _title(name: str, scenario: dict) -> str:
    return scenario.get("title") or name.replace("_", " ")


class Library:
    """Reads check-up folders under ``root`` (newest first), with a small cache."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._runs: dict[str, RunEntry] = {}
        self._analysis_cache: dict[tuple[str, float], RunAnalysis] = {}

    # ---- check-ups -----------------------------------------------------------------------
    def checkup_folders(self) -> list[Path]:
        """Result folders (each holding one sub-folder per policy), newest first."""
        if not self.root.is_dir():
            return []
        found = [
            path
            for path in self.root.iterdir()
            if path.is_dir() and any(path.glob("*/checkup.json"))
        ]
        return sorted(found, key=lambda path: path.stat().st_mtime, reverse=True)

    def newest_folder(self, robot: str) -> Path | None:
        for folder in self.checkup_folders():
            first = next(folder.glob("*/checkup.json"))
            if json.loads(first.read_text(encoding="utf-8")).get("robot") == robot:
                return folder
        return None

    def robots_with_results(self) -> set[str]:
        return {robot for robot in all_robots() if self.newest_folder(robot) is not None}

    # ---- runs ----------------------------------------------------------------------------
    def _entry(self, run_dir: Path, robot: str, policy: str) -> RunEntry:
        meta_file = run_dir / "robot_run.json"
        stamp = meta_file.stat().st_mtime
        key = (str(run_dir), stamp)
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        scenario = meta["scenario"]
        if key not in self._analysis_cache:
            self._analysis_cache[key] = analyze(RobotRun.read(run_dir))
        entry = RunEntry(
            id=_run_id(run_dir),
            robot=robot,
            policy=policy,
            folder=run_dir,
            name=run_dir.name,
            title=_title(run_dir.name, scenario),
            kind=_kind(run_dir.name),
            analysis=self._analysis_cache[key],
            scenario=scenario,
            mtime=stamp,
            what_if=(meta.get("provenance") or {}).get("what_if"),
        )
        self._runs[entry.id] = entry
        return entry

    def runs(self, robot: str) -> list[RunEntry]:
        """Saved runs of the robot's newest check-up: baselines first, then shoves."""
        folder = self.newest_folder(robot)
        if folder is None:
            return []
        entries = []
        for checkup_file in sorted(folder.glob("*/checkup.json")):
            policy = checkup_file.parent.name
            for meta in sorted((checkup_file.parent / "runs").glob("*/robot_run.json")):
                entries.append(self._entry(meta.parent, robot, policy))
        rank = {word: index for index, word in enumerate(_ORDER)}
        info = robot_info(robot)
        entries.sort(
            key=lambda e: (rank.get(e.kind, len(rank)), info.policy(e.policy).gets_up, e.name)
        )
        _not_stuck_when_standing_is_normal(entries)
        _link_pairs(entries)
        return entries

    def run(self, run_id: str) -> RunEntry:
        """A run by id (the listing is rebuilt once if the id is new)."""
        if run_id not in self._runs:
            for robot in all_robots():
                self.runs(robot)
        return self._runs[run_id]

    def load(self, run_id: str) -> tuple[RunEntry, RobotRun]:
        entry = self.run(run_id)
        return entry, RobotRun.read(entry.folder)

    # ---- results summary -----------------------------------------------------------------
    def checkup_summary(self, robot: str) -> dict | None:
        """Per policy: baseline verdict, shove results and conditions, linked to run ids."""
        folder = self.newest_folder(robot)
        if folder is None:
            return None
        info = robot_info(robot)
        entries = {(e.policy, e.name): e for e in self.runs(robot)}
        policies = []
        for checkup_file in sorted(folder.glob("*/checkup.json")):
            checkup = Checkup.model_validate_json(checkup_file.read_text(encoding="utf-8"))
            policy = checkup.policy

            def run_id(name: str | None, policy: str = policy) -> str | None:
                entry = entries.get((policy, name)) if name else None
                return entry.id if entry else None

            policies.append(
                {
                    "policy": policy,
                    "title": info.policy(policy).title,
                    "summary": info.policy(policy).summary,
                    "getsUp": info.policy(policy).gets_up,
                    "baseline": checkup.baseline.verdict,
                    "baselineRun": run_id(checkup.baseline_run),
                    "neverFallsUpTo": checkup.never_falls_up_to_n,
                    "neverStaysDownUpTo": checkup.never_stays_down_up_to_n,
                    "shoves": [
                        {
                            "force": row.force_n,
                            "total": row.total,
                            "stayedUp": row.stayed_up,
                            "gotUp": row.got_up,
                            "stayedDown": row.stayed_down,
                            "fallRun": run_id(row.example_fall_run),
                            "okRun": run_id(row.example_ok_run),
                        }
                        for row in checkup.shoves
                    ],
                    "conditions": [
                        _condition_row(c, entries.get((policy, c.run)), run_id(c.run))
                        for c in checkup.conditions
                    ],
                }
            )
        policies.sort(key=lambda p: p["getsUp"])  # the policy that stays down first
        return {"robot": robot, "folder": folder.name, "policies": policies}
