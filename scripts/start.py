#!/usr/bin/env python3
"""Bootstrap and launch Creature Lab from a fresh checkout."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from _process_utils import port_is_open, taskkill_tree

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORT = 8080
VENV_DIR = ROOT / ".venv"
#: What the browser app (and the classic editor it opens) import. If any is missing the extras
#: are not installed. Everything here ships as prebuilt wheels on Windows, macOS and Linux, so a
#: first launch never needs a compiler. PyBullet (the `sim` extra) is not in this list on purpose.
APP_PROBE = "import fastapi, uvicorn, mujoco, onnxruntime, imageio, PIL, viser, trimesh"
APP_EXTRAS = ["--extra", "viz", "--extra", "web", "--extra", "robots"]
#: The classic editor runs on MuJoCo when PyBullet is absent, so it needs the same wheels.
BUILD_PROBE = (
    "import viser, trimesh\ntry:\n    import pybullet\nexcept ImportError:\n    import mujoco"
)
#: The read-only demo viewer simulates with PyBullet.
DEMO_PROBE = "import viser, trimesh, pybullet"
DEMO_EXTRAS = ["--extra", "sim", "--extra", "viz"]
#: The Python a first install asks for: the newest interpreter often has no wheel for some
#: dependency yet (onnxruntime on Python 3.15), and uv would pick it if it were the only one found.
PREFERRED_PYTHON = "3.12"
MODE_SETUP = {
    "app": (APP_PROBE, APP_EXTRAS),
    "build": (BUILD_PROBE, APP_EXTRAS),
    "demo": (DEMO_PROBE, DEMO_EXTRAS),
}


#: What a failed install usually means, matched against the installer's own output.
INSTALL_ADVICE: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"os error 206|path too long|filename or extension is too long|MAX_PATH|"
            r"MSB3491|path, file name, or both are too long|fatal error C1083|Filename too long",
            re.IGNORECASE,
        ),
        "A file path inside this folder is longer than Windows allows (260 characters). Move the "
        "Creature Lab folder somewhere with a short path, for example C:\\creature-lab, and run "
        "the launcher again. (Or turn on Windows long paths.)",
    ),
    (
        re.compile(
            r"Microsoft Visual C\+\+|vcvarsall|CMAKE_CXX_COMPILER|gcc: (command )?not found|"
            r"command 'gcc' failed|xcrun: error|Python\.h: No such file|Failed to build",
            re.IGNORECASE,
        ),
        "A package had to be compiled and this computer has no C++ build tools. The browser app "
        "and the editor do not need that: they use prebuilt packages. Only PyBullet (the optional "
        "`sim` extra) compiles. Skip it, or install build tools first (Windows: Microsoft C++ "
        "Build Tools; macOS: `xcode-select --install`; Linux: `sudo apt install build-essential`).",
    ),
    (
        re.compile(r"No space left on device|os error 112|not enough space", re.IGNORECASE),
        "The disk is full. Free a few GB and run the launcher again; what already downloaded is "
        "kept.",
    ),
    (
        re.compile(
            r"dns error|error sending request|connection (refused|reset|closed)|timed out|"
            r"certificate verify|failed to download",
            re.IGNORECASE,
        ),
        "The installer could not download packages. Check your network or proxy and run the "
        "launcher again; what already downloaded is kept.",
    ),
]


def explain_install_failure(output: str) -> str | None:
    """Plain advice for the first known cause in an installer's output, or None."""
    for pattern, advice in INSTALL_ADVICE:
        if pattern.search(output):
            return advice
    return None


def first_install_python(venv_exists: bool) -> list[str]:
    """uv arguments that choose the interpreter for a first install; an existing venv is kept."""
    return [] if venv_exists else ["--python", PREFERRED_PYTHON]


def check_python() -> None:
    """Fail early with a clear message when Python is too old."""
    if sys.version_info < (3, 11):  # noqa: UP036 - friendly launcher error for old Python.
        version = ".".join(str(part) for part in sys.version_info[:3])
        raise SystemExit(
            f"Creature Lab needs Python 3.11 or newer. This launcher is using Python {version}."
        )


def command_text(command: list[str]) -> str:
    """Return a readable command line for logs."""
    return " ".join(str(part) for part in command)


def print_header(title: str) -> None:
    print(f"\n== {title} ==", flush=True)


def format_exit_code(code: int) -> str:
    """Render a subprocess exit code readably.

    Windows reports an interrupted/killed process as -1, which Python's SystemExit
    then surfaces to the shell as the unsigned wraparound 4294967295 - meaningless
    to a reader. Call this out explicitly instead of printing the raw number.
    """
    if code in (-1, 0xFFFFFFFF):
        return "interrupted"
    return str(code)


def _run_streaming(command: list[str]) -> tuple[int, str]:
    """Run a command, show its output as it arrives, and return (exit code, the last lines)."""
    tail: list[str] = []
    with subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    ) as proc:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            tail.append(line)
            del tail[:-400]
        return proc.wait(), "".join(tail)


def run_step(
    title: str,
    command: list[str],
    *,
    dry_run: bool = False,
    failure_hint: str,
    explain: bool = False,
) -> None:
    """Run one setup/check step with readable context and failure hints.

    ``explain`` also reads the command's output, so a failure it recognizes (a path too long for
    Windows, a missing compiler, a full disk, no network) is explained in plain words.
    """
    print_header(title)
    print(f"$ {command_text(command)}", flush=True)
    if dry_run:
        return

    try:
        if explain:
            code, output = _run_streaming(command)
            if code != 0:
                raise subprocess.CalledProcessError(code, command, output=output)
        else:
            subprocess.run(command, cwd=ROOT, check=True)
    except FileNotFoundError as exc:
        print(f"\nCould not find executable: {command[0]}", file=sys.stderr)
        print(failure_hint, file=sys.stderr)
        raise SystemExit(127) from exc
    except subprocess.CalledProcessError as exc:
        print(
            f"\nThe '{title}' step failed with exit code {format_exit_code(exc.returncode)}.",
            file=sys.stderr,
        )
        advice = explain_install_failure(exc.output) if isinstance(exc.output, str) else None
        if advice:
            print(f"\nWhat to do: {advice}", file=sys.stderr)
        print(failure_hint, file=sys.stderr)
        raise SystemExit(exc.returncode if 0 <= exc.returncode < 256 else 1) from exc


def _terminate_tree(proc: subprocess.Popen) -> None:
    """Force-kill a process and everything it spawned.

    `uv run creature-lab demo` is itself a chain (uv -> creature-lab.exe -> the
    viser server); Popen.terminate() only signals the immediate child, which can
    leave grandchildren running. On Windows those orphans keep an exclusive lock
    on files under .venv, breaking the next `uv sync`. `taskkill /T` kills the
    whole tree; on other platforms a plain terminate/kill is enough since we run
    without a shell and there's no equivalent orphaning.
    """
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        taskkill_tree(proc.pid)
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_launch_step(
    command: list[str], *, title: str = "Launch viewer", dry_run: bool, failure_hint: str
) -> None:
    """Run the long-lived viewer/editor process, guaranteeing its tree is cleaned up.

    Unlike `run_step`, this uses Popen directly so a Ctrl+C (or a hung/crashed
    child) always goes through `_terminate_tree` in `finally` - see its docstring
    for why that matters.
    """
    print_header(title)
    print(f"$ {command_text(command)}", flush=True)
    if dry_run:
        return

    try:
        proc = subprocess.Popen(command, cwd=ROOT)
    except FileNotFoundError as exc:
        print(f"\nCould not find executable: {command[0]}", file=sys.stderr)
        print(failure_hint, file=sys.stderr)
        raise SystemExit(127) from exc

    returncode: int | None = None
    try:
        returncode = proc.wait()
    except KeyboardInterrupt:
        returncode = None
    finally:
        _terminate_tree(proc)

    if returncode is None:
        print("\nStopped Creature Lab.")
        return
    if returncode != 0:
        print(
            f"\nThe {title!r} step failed with exit code {format_exit_code(returncode)}.",
            file=sys.stderr,
        )
        print(failure_hint, file=sys.stderr)
        raise SystemExit(returncode if 0 <= returncode < 256 else 1)


def _is_interactive() -> bool:
    return sys.stdin.isatty()


def _confirm(prompt: str) -> bool:
    if not _is_interactive():
        return False
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def find_stray_venv_processes() -> list[tuple[int, str]]:
    """Windows only: processes still running from this project's .venv.

    Windows locks an .exe/.dll while it runs, so a process orphaned by a previous
    interrupted launch (see `_terminate_tree`) can make `uv sync` fail with
    "os error 32" on the next run. This gives the sync step something concrete to
    detect and offer to clean up instead of a bare file-in-use error.
    """
    if sys.platform != "win32":
        return []
    venv_str = str(VENV_DIR).replace("'", "''")
    script = (
        "Get-Process | Where-Object { $_.Path -and "
        "$_.Path.StartsWith('" + venv_str + "', [System.StringComparison]::OrdinalIgnoreCase) } "
        "| Select-Object Id, Path | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    processes: list[tuple[int, str]] = []
    for item in data:
        pid = item.get("Id")
        if pid is not None:
            processes.append((int(pid), str(item.get("Path", ""))))
    return processes


def clear_stray_processes(processes: list[tuple[int, str]]) -> None:
    for pid, _ in processes:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)
    time.sleep(0.5)  # give Windows a beat to release the file handles


def run_sync_step(uv: list[str], sync_args: list[str], *, dry_run: bool, auto_yes: bool) -> None:
    """Install dependencies, recovering automatically from a stray-process file lock."""
    hint = (
        "Dependency installation failed. Check your network connection, then run the "
        "`uv sync` command shown above manually."
    )
    try:
        run_step(
            "Install dependencies",
            [*uv, *sync_args],
            dry_run=dry_run,
            failure_hint=hint,
            explain=True,
        )
    except SystemExit:
        if dry_run or sys.platform != "win32":
            raise
        stray = find_stray_venv_processes()
        if not stray:
            raise
        print(
            "\nA previous Creature Lab viewer looks like it is still running and has "
            "a file in .venv locked:",
            file=sys.stderr,
        )
        for pid, path in stray:
            print(f"  PID {pid}: {path}", file=sys.stderr)
        if auto_yes or _confirm("Stop the process(es) above and retry install?"):
            clear_stray_processes(stray)
            run_step(
                "Install dependencies (retry)",
                [*uv, *sync_args],
                dry_run=dry_run,
                failure_hint=hint,
                explain=True,
            )
        else:
            print(
                "Stop them manually (e.g. `Stop-Process -Id <PID> -Force`) and rerun, "
                "or pass --yes to do this automatically.",
                file=sys.stderr,
            )
            raise


def ensure_mode_extras(uv: list[str], mode: str, *, dry_run: bool, auto_yes: bool) -> None:
    """Install the extras a launch mode needs when the environment lacks them.

    The launchers (run.ps1, run.sh) install the app's extras and then call this script with
    --skip-sync, so a different mode (the PyBullet demo viewer) may still need more.
    `--inexact` keeps whatever is installed already, so this only adds.
    """
    probe_code, extras = MODE_SETUP[mode]
    probe = [*uv, "run", "--frozen", "--no-sync", "python", "-c", probe_code]
    if not dry_run and subprocess.run(probe, cwd=ROOT, capture_output=True).returncode == 0:
        return
    if "sim" in extras:
        print(
            "\nThis mode simulates with PyBullet. Outside Linux with Python 3.11 it is built "
            "from source (several minutes) and needs a C++ compiler.",
            flush=True,
        )
    run_sync_step(
        uv,
        ["sync", "--frozen", "--inexact", *extras],
        dry_run=dry_run,
        auto_yes=auto_yes,
    )


def uv_command(explicit: str | None) -> list[str]:
    """Resolve uv as either a PATH executable or a Python module."""
    if explicit:
        return [explicit]

    uv_path = shutil.which("uv")
    if uv_path:
        return [uv_path]

    probe = subprocess.run(
        [sys.executable, "-m", "uv", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if probe.returncode == 0:
        return [sys.executable, "-m", "uv"]

    raise SystemExit(
        "uv is required to install and run Creature Lab.\n\n"
        "Install uv, then rerun this script:\n"
        "  Windows PowerShell: irm https://astral.sh/uv/install.ps1 | iex\n"
        "  macOS/Linux:       curl -LsSf https://astral.sh/uv/install.sh | sh\n"
        "  pip fallback:      python -m pip install uv"
    )


def choose_port(port: int, *, explicit: bool) -> int:
    """Choose a viewer port, avoiding stale local servers on the default port."""
    if not port_is_open(port):
        return port

    if explicit:
        raise SystemExit(
            f"Port {port} is already in use. Stop the process using it or rerun with "
            f"`--port {port + 1}`."
        )

    for candidate in range(port + 1, port + 20):
        if not port_is_open(candidate):
            print(
                f"Port {port} is already in use; using http://localhost:{candidate} instead.",
                flush=True,
            )
            return candidate

    raise SystemExit("No free viewer port found in the 8080-8099 range. Rerun with --port <port>.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Install the starter dependencies, check the environment, and launch "
            "Creature Lab in a browser."
        )
    )
    parser.add_argument(
        "--mode",
        choices=["app", "build", "demo"],
        help=(
            "What to launch: the browser app with the real robots, check-ups and replays "
            "(default), the classic build/setup screen where you configure a creature "
            "(the default when you pass --creature, --creature-path or --task), or the "
            "read-only demo playback viewer."
        ),
    )
    parser.add_argument(
        "--creature",
        help=(
            "Starting point. In --mode build: a preset (quadruped, hexapod, worm, "
            "humanoid). In --mode demo: a built-in creature (quadruped, worm, tripod). "
            "Default: quadruped."
        ),
    )
    parser.add_argument(
        "--creature-path",
        type=Path,
        help="Path to a CreatureSpec JSON file to open/edit. Overrides --creature.",
    )
    parser.add_argument("--task", type=Path, help="Optional TaskSpec JSON path.")
    parser.add_argument("--port", type=int, help="Viser server port. Default: 8080.")
    parser.add_argument(
        "--once",
        "--no-hold",
        dest="hold",
        action="store_false",
        help="Run one pass, save the trace, and exit instead of keeping the viewer open.",
    )
    parser.add_argument(
        "--hold",
        dest="hold",
        action="store_true",
        default=True,
        help="Keep the viewer open and looping until Ctrl+C. This is the default.",
    )
    parser.add_argument(
        "--open-browser",
        dest="open_browser",
        action="store_true",
        default=True,
        help="Open the viewer URL in your default browser. This is the default.",
    )
    parser.add_argument(
        "--no-open-browser",
        dest="open_browser",
        action="store_false",
        help="Print the viewer URL but do not open a browser tab.",
    )
    parser.add_argument("--skip-sync", action="store_true", help="Do not run uv sync first.")
    parser.add_argument(
        "--skip-doctor", action="store_true", help="Do not run creature-lab doctor."
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Install all optional extras instead of only the demo extras.",
    )
    parser.add_argument("--uv", help="Path to a uv executable.")
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help=(
            "Automatically confirm recovery actions (e.g. stopping a stray previous "
            "viewer process that is locking .venv) without prompting."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the commands without running them.",
    )

    args = parser.parse_args()
    if args.creature_path and args.creature:
        parser.error("--creature-path cannot be combined with --creature")
    if args.mode is None:
        # Asking for a particular creature or task means the classic screens.
        wants_classic = args.creature or args.creature_path or args.task
        args.mode = "build" if wants_classic else "app"
    if args.mode == "app" and (args.creature or args.creature_path or args.task):
        parser.error("--creature, --creature-path and --task apply to --mode build or demo")
    args.creature = args.creature or "quadruped"
    if args.creature_path and not args.creature_path.exists():
        parser.error(f"--creature-path does not exist: {args.creature_path}")
    if args.task and not args.task.exists():
        parser.error(f"--task does not exist: {args.task}")
    return args


def main() -> None:
    check_python()
    args = parse_args()
    uv = uv_command(args.uv)
    requested_port = args.port is not None
    port = choose_port(args.port or DEFAULT_PORT, explicit=requested_port)
    url = f"http://localhost:{port}"

    label = {"app": "App", "build": "Build editor", "demo": "Demo viewer"}[args.mode]
    print("Creature Lab starter")
    print(f"Repository: {ROOT}")
    print(f"{label} URL: {url}")
    print("Press Ctrl+C in this terminal to stop.")

    if not args.skip_sync:
        extras = MODE_SETUP[args.mode][1]
        sync_args = [
            "sync",
            "--frozen",
            *first_install_python(VENV_DIR.exists()),
            *(["--all-extras"] if args.full else extras),
        ]
        run_sync_step(uv, sync_args, dry_run=args.dry_run, auto_yes=args.yes)
    else:
        ensure_mode_extras(uv, args.mode, dry_run=args.dry_run, auto_yes=args.yes)

    if not args.skip_doctor:
        run_step(
            "Check environment",
            [*uv, "run", "creature-lab", "doctor"],
            dry_run=args.dry_run,
            failure_hint=(
                "Environment checks failed. The table above should show which optional "
                "component is missing or broken."
            ),
        )

    if not args.open_browser:
        print(f"Open this URL manually after launch: {url}")

    if args.mode == "app":
        launch_command = [*uv, "run", "creature-lab", "app", "--port", str(port)]
        launch_command.append("--open-browser" if args.open_browser else "--no-open-browser")
        title = "Launch app"
    elif args.mode == "build":
        launch_command = [*uv, "run", "creature-lab", "build", "--port", str(port)]
        launch_command.append("--open-browser" if args.open_browser else "--no-open-browser")
        if args.creature_path:
            launch_command.append(str(args.creature_path))
        else:
            launch_command.extend(["--preset", args.creature])
        if args.task:
            launch_command.extend(["--task", str(args.task)])
        if not args.hold:
            print("note: --once/--no-hold only applies to --mode demo; ignoring for build.")
        title = "Launch build editor"
    else:
        launch_command = [*uv, "run", "creature-lab", "demo", "--port", str(port)]
        if args.open_browser:
            launch_command.append("--open-browser")
        if args.creature_path:
            launch_command.append(str(args.creature_path))
        else:
            launch_command.extend(["--creature", args.creature])
        if args.task:
            launch_command.extend(["--task", str(args.task)])
        if not args.hold:
            launch_command.append("--no-hold")
        title = "Launch demo viewer"

    run_launch_step(
        launch_command,
        title=title,
        dry_run=args.dry_run,
        failure_hint=(
            f"Launch failed. Try `python scripts/start.py --port {port + 1}` "
            "or run `uv run creature-lab doctor` for details."
        ),
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped Creature Lab.")
        sys.exit(130)
