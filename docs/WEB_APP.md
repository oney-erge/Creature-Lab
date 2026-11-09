# Browser app

The browser app is the front door: pick a real robot, watch a saved shove in 3D, read why it
fell, and run a fresh check-up, all in one tab.

<p align="center">
  <img src="assets/app-microduck.webp" width="800" alt="The Creature Lab browser app showing a Microduck robot on the floor in slow motion after a 3 N shove, with the run history on the left and the explanation and shove results on the right." />
</p>

<p align="center"><sub>Simulation. Microduck model by Pollen Robotics, CC BY-NC-SA 4.0.</sub></p>

## Start it

```bash
./run.sh                          # Linux; macOS: ./run.command; Windows: .\run.bat
uv run creature-lab app           # after `uv sync --inexact --extra web --extra robots`
```

The launcher adds the `web` and `robots` extras by itself the first time. The app opens at
`http://localhost:8080` (the next free port if that one is busy). It reads and writes check-up
folders under `outputs/checkup`; pass `--checkups DIR` to use another one.

`python scripts/start.py --creature humanoid` (or `--mode build`) still opens the classic
build editor.

## What you can do

- **Choose a robot.** Microduck and the Unitree G1 are the first choices. A robot that is not
  downloaded yet shows its license first. Nothing is downloaded until you tick that you have
  read it.
- **Watch a run.** The robot is drawn from its real meshes with a follow camera. The first run
  shown is a middle-strength shove that the robot got up from. Playback slows to 0.3x through
  the shove and the fall, as in the films; you can switch that off, pause, scrub, or change speed
  (arrow keys, Home and End work on the timeline).
- **See why.** Teal and red outlines show the feet's support area, the amber disc is where the
  body's weight would land, and the orange arrow is the shove. The panel on the right states the
  cause in words with the three numbers behind it.
- **Compare policies.** Switch between a robot's policies and open any shove in the matrix.
  Every card in the history is a run you can watch.
- **Run a check-up.** *Run check-up* starts the same run as `creature-lab robots checkup` in the
  background and shows its progress. When it finishes, the app opens the new results.
- **Build your own.** This opens the classic build editor for your own creature (it needs the
  `sim` and `viz` extras).

## How it is built

| Part | Where | Notes |
| --- | --- | --- |
| Server | `creature_lab/web/` | FastAPI. `library.py` reads saved check-ups, `scene.py` turns a MuJoCo model and a run into binary arrays, `jobs.py` runs downloads and check-ups, `thumbs.py` renders cached thumbnails, `builder.py` starts the classic editor. |
| Front end | `web-ui/` | React, three.js, Vite and TypeScript. |
| Built bundle | `creature_lab/web/static/` | **Committed**, so users never need Node. Rebuild it after changing `web-ui/` (see [web-ui/README.md](../web-ui/README.md)); CI fails when it is stale. |

The server sends meshes once per robot and poses per run as plain little-endian arrays (the layout
is documented in `scene.py`), not as JSON. The browser interpolates between frames, so a run
plays smoothly at any speed.

### Safety

The app is meant for your own machine.

- It listens on `127.0.0.1` and refuses requests whose `Host` is not `localhost`, `127.0.0.1` or
  `::1`, so a web page on another site cannot reach it through DNS rebinding.
- Anything that changes state (download, check-up, builder) must carry an `X-Creature-Lab`
  header. A web page on another origin cannot add one without a CORS preflight, and the server
  sends no CORS headers.
- The browser never supplies a file path. Runs are addressed by opaque ids the server derived,
  and static files cannot escape the bundle folder.
- Robot downloads need an explicit license acknowledgement in the request, in addition to the
  dialog.
- `--host` other than a loopback address prints a warning: the app can start CPU-heavy jobs and
  has no sign-in.

## Limits

- It shows simulations of the robots, not the hardware.
- Software WebGL (a machine without a GPU) draws it, but slowly.
- Building a creature is still the classic Viser editor, opened in a second tab.
