# Browser app front end

Source of the Creature Lab browser app (React, three.js, Vite, TypeScript). `npm run build` writes
`../creature_lab/web/static/`. That folder is **committed**, so people who install or clone
Creature Lab never need Node. See [docs/WEB_APP.md](../docs/WEB_APP.md) for what the app does.

You only need Node when you change something in this folder. Node 22.12 or newer is
recommended (Vite warns on older 22.x).

```bash
cd web-ui
npm ci
npm run dev        # http://localhost:5173, proxies /api to the Python server on 127.0.0.1:8080
npm run typecheck
npm test           # playback, decoding and formatting logic
npm run build      # rebuilds ../creature_lab/web/static
```

Run the server next to it in another terminal: `uv run creature-lab app --no-open-browser`.
The dev proxy uses `127.0.0.1` on purpose: `localhost` can resolve to IPv6 on Windows and stall.

Commit the rebuilt `creature_lab/web/static/` together with the source change. CI rebuilds the
bundle and fails when the committed one differs.

## Layout

| File | Role |
| --- | --- |
| `src/App.tsx` | State, job polling, and the three columns |
| `src/components/` | `Library` (robots and run history), `Stage` (3D view), `Timeline`, `Inspector`, `LicenseDialog` |
| `src/robotView.ts` | The three.js scene: lights, floor, robot meshes, support and shove overlays, follow camera |
| `src/playback.ts` | The clock: speed, auto slow-motion near the shove and fall, looping |
| `src/decode.ts` | Reads the server's binary arrays; keep in step with `creature_lab/web/scene.py` |
| `src/types.ts`, `src/api.ts` | The JSON the server returns, and the calls (with the `X-Creature-Lab` header) |
| `src/logic.test.ts` | Vitest tests for the logic above (no browser needed) |

## Windows note

If `npm ci` succeeds but Vite fails with `Cannot find module '@rolldown/binding-win32-x64-msvc'`,
npm skipped the platform package (an npm optional-dependency bug). Install it without saving:

```powershell
npm install --no-save @rolldown/binding-win32-x64-msvc@1.2.16
```
