# Job and editor lifecycle boundaries

- `creature_lab.web.jobs.Jobs` admits at most one active or unresolved download or check-up per
  kind and robot in one server process. License acknowledgement and asset verification remain
  with the existing download endpoint and fetcher.
- Check-ups retain their owned subprocess. A stop request is saved before a signal is sent and
  remains `cancelling` until the worker observes exit. A finished report may win the race. If
  saving the request fails, no signal is sent; if signaling fails, the user sees the failure and
  can retry. Downloads have no safe stop control.
- Job snapshots are atomically written under the check-up folder's `.jobs`. A check-up that was
  active at restart becomes `interrupted` with an unknown outcome; the server neither signals an
  old PID nor starts another attempt until the user confirms the process has stopped. Downloads
  interrupted by restart can be retried. Unreadable records block new jobs until reviewed.
- The classic editor's `EditorJobManager` owns one job and distinguishes a requested stop from
  the worker's terminal state. `BuildControls.lifecycle_snapshot()` is a read-only in-process
  projection of current input, job, result applicability and playback; it is not a network API.
  A result for inputs changed while the job ran is not applied to the current design.

These are process-local boundaries, not cross-process fencing. Older application versions do
not honor the new recovery records, so stop the current server and review any interrupted work
before a downgrade. `tests/test_web_server.py`, `tests/test_editor_jobs.py` and
`tests/test_editor_controls.py` exercise selected boundaries; real robot policies and hardware
have separate verification requirements.
