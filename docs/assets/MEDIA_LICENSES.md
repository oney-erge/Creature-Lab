# Media in this folder

| File | Shows | License |
| --- | --- | --- |
| `checkup-microduck.webp`, `.gif`, `.mp4` | Pollen Robotics' Microduck model, rendered by Creature Lab | **CC BY-NC-SA 4.0** |
| `app-microduck.webp`, `app-compare.webp` | Screenshots of the browser app showing Pollen Robotics' Microduck model | **CC BY-NC-SA 4.0** |
| `app-build.webp` | Screenshot of the browser app's creature designer (Creature Lab's own shapes) | Apache-2.0 |
| `checkup-unitree-g1.webp`, `.gif`, `.mp4` | Unitree Robotics' G1 model, rendered by Creature Lab | BSD 3-Clause model; renders Apache-2.0 |
| `creature-lab-demo.gif` | A screen recording of the browser app showing Unitree's G1 model | BSD 3-Clause model; recording Apache-2.0 |
| The tour video ([oneyerge.com/media/creature-lab-tour.mp4](https://oneyerge.com/media/creature-lab-tour.mp4), not in the repository) | Screen recordings of the app with both robots | **CC BY-NC-SA 4.0** (it shows the Microduck) |
| `social-preview.png` | The image for the GitHub link card (a frame of the G1 render plus text) | BSD 3-Clause model; image Apache-2.0 |
| `creature-lab-logo.svg`, `demo.gif`, `quickstart.ipynb` | Creature Lab's own work | Apache-2.0 |

The Microduck files (including the app screenshot) are adaptations (renders) of the Microduck 3D meshes by
[Pollen Robotics](https://github.com/pollen-robotics/microduck_rl), which are licensed
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). So these renders are
licensed CC BY-NC-SA 4.0 too: credit Pollen Robotics, use them non-commercially, and share any
adaptation under the same license. Changes made: the meshes were posed by a simulation and
rendered with lighting, camera motion and on-screen labels.

The G1 model comes from [unitreerobotics/unitree_rl_gym](https://github.com/unitreerobotics/unitree_rl_gym)
(BSD 3-Clause, Copyright Unitree Robotics).

The app also ships one of these, `unitree_g1.webp`, as the looping clip on its first screen (in
`creature_lab/web/static/clips`). Only the G1 clip is bundled; the Microduck media are CC BY-NC-SA and
are never part of the package.

All of these are simulations, not footage of the hardware. Neither company is affiliated with
or endorses Creature Lab.

Regenerate them with `creature-lab robots checkup <robot> --film`, then
`creature-lab robots loop <results> --output docs/assets/checkup-<robot>.webp` (or `.gif`).

The app recording and the tour come from `scripts/media/record_app.py` (drives the real app in a
headless browser and records each scene) and `scripts/media/compose_app.py` (cuts, captions and
encodes). The captions quote numbers from the runs on screen, so check them again after recording
a different check-up (`compose_app.py still tour`).
