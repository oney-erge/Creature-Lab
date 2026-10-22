# Security Policy

## Scope

Creature Lab is a local lab for one person on their own machine. The viewer, replay, compare, and
build-editor servers listen on `127.0.0.1` by default, so only programs on the same computer can
connect. `--host` (or the `CREATURE_LAB_HOST` environment variable) changes that, and the command
prints a warning when it is not a loopback address. The provided Docker Compose file publishes the
port on `127.0.0.1` only.

There are no user accounts, sign-in, TLS, or rate limiting. Do not expose it to a network or the
internet.

## What the build editor can do

Anyone who can reach the editor's port can use it as you:

- **Read and write files by path.** The editor's Project folder has **Open path** and **Save path**
  fields. Open reads the file at that path as a creature, URDF, or project, and Save writes a creature
  (JSON, URDF, or MJCF) to the path you give it, with the permissions of the user running Creature Lab.
- **Run simulations.** Simulate, Robustness, Qualify, and Re-fit start CPU-heavy jobs and write runs
  under the runs folder.

Keep the default loopback address, and run Creature Lab as a normal user.

## Docker

The image sets `CREATURE_LAB_HOST=0.0.0.0` so the server is reachable through Docker's port mapping.
`compose.yaml` maps that port to `127.0.0.1` on the host, which keeps it local. Changing the mapping
changes the security boundary. A plain `docker run -p 8080:8080` publishes it on every interface; use
`-p 127.0.0.1:8080:8080` instead.

## What it does with your data

Creature specs, tasks, traces, reports, and design packs stay in the folders you point them at
(`runs/` and `outputs/` by default, both ignored by Git). The simulators and viewers make no network
requests. The one exception is `creature-lab ask` with the optional `llm` extra: it sends your goal
and the design state to whichever model endpoint you configure, and `--offline` (the built-in
policy) sends nothing. Keep API keys in environment variables, not in files you commit.

## Known limits

| Limit | Why it matters |
|---|---|
| No authentication | Whoever can reach the port can use the editor, including its file Open and Save fields. |
| Plain HTTP | Nothing on the connection is protected if it crosses a network. |
| No rate or concurrency limits | A connected client can start many simulations and use all CPU and disk. |
| Creature and task files are trusted input | Open files you trust; a malformed file is rejected by validation, but Creature Lab is not a sandbox for hostile files. |

## Reporting a vulnerability

Use the **Report a vulnerability** button on the repository's Security tab instead of opening a
public issue. GitHub keeps the report private between you and the maintainer.

If that button is not available, open a minimal issue asking for a private contact method. Do not put
exploit details, API keys, or local paths in the public issue.

## Disclaimer

Creature Lab is provided without warranty under the [Apache License 2.0](LICENSE). It writes files on
the machine it runs on; keep recoverable copies of anything important.
