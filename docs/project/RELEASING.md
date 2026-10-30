# Releasing Creature Lab

Public publication is intentionally separate from implementation. The release workflow builds
and uploads distributions for inspection; it does not publish to PyPI automatically.

## Experimental Windows preview

The [Windows preview](https://github.com/oney-erge/Creature-Lab/releases/tag/preview-windows-2026-10-30)
contains its source commit, wheel, checksums, and `refresh_archive.py`. The script substitutes
the wheel into the earlier `preview-0.2.0` Windows archive; it does not construct that runtime
from scratch or verify startup. Download those inputs and run:

```powershell
python refresh_archive.py --base creature-lab-windows-x64-portable-unverified.zip `
  --base-sha256 f809e61a11dd4c290b7757d43ce079d681c70c034a507b90a3afdf27276b8fa5 `
  --wheel creature_lab-0.2.0-py3-none-any.whl --output refreshed.zip `
  --root creature-lab --commit 0c2e0c1572abfb439a9ade6b4ec2911d34d356a0
```

The script rejects a mismatched base and checks the wheel members in its output. The source
lock and project metadata must match the base's dependency inputs; the script does not verify
that itself. The base includes a locally compiled PyBullet wheel. A complete from-scratch
runtime recipe and clean-machine verification remain outstanding.

## 1. Freeze And Verify

```bash
uv sync --inexact --all-extras
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run creature-lab doctor
uv run creature-lab zoo validate-all
uv run creature-lab zoo check-showcases
uv run python scripts/browser_smoke.py
uv build
```

Confirm `VERSION`, `pyproject.toml`, `uv.lock`, `CITATION.cff`, and the changelog agree. Review the
wheel contents and install it into a clean environment outside the checkout.

## 2. Clean-Install Smoke

```bash
uv venv --seed .release-venv
uv pip install --python .release-venv dist/creature_lab-*.whl
.release-venv/bin/creature-lab --help
```

Use `.release-venv/Scripts/creature-lab.exe` on Windows. Install `[sim,viz]` when testing the full
first-run editor rather than the dependency-light CLI.

## 3. Public Publication Gate

Before publishing:

- Configure a protected GitHub `pypi` environment and PyPI trusted publisher.
- Confirm the repository README, demo media, package metadata, and release notes describe the
  same measured behavior.
- Download the CI-built artifacts and compare their hashes with the files to be published.
- Create the signed `v0.2.0` tag only after every required CI job passes.
- Publish once, then test the public install from a clean directory:

```bash
uvx --from "creature-lab[sim,viz]" creature-lab doctor
uvx --from "creature-lab[sim,viz]" creature-lab zoo run quadruped
```

Attach wheel/source distributions and a short autopsy example to the GitHub release. Do not
commit generated runs, packs, media exports, environments, or provider credentials.
