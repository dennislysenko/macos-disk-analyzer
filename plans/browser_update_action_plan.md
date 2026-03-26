# Browser Update Workflow Plan

## Goal
- Allow the curses browser to mark one or more directories for refresh (`U`/`M`) and display their status.
- Add a submit action that spawns a blocking re-analysis which writes a *new* timestamped run containing only the selected folders.
- Leave existing runs untouched while clearly communicating the new run and any limitations.

## Assumptions
- The original analyzer options (`directory`, `min-size`, `sudo`, `quiet`) should be reused for selective reruns.
- Re-analyzing multiple arbitrary subpaths is acceptable even if parents are not recomputed; we can optionally re-run parents for consistency later.
- Blocking submit is acceptable (browser exits, runs analyzer, then relaunches).

## Phase 1 — Persist Analyzer Metadata
1. Extend `disk_analyzer.py` to emit a `run_metadata.json` beside each `disk_usage.txt`. Include:
   - Root directory analyzed.
   - Timestamp folder name.
   - Analyzer flags (`min-size`, `sudo`, `quiet`).
   - Analyzer version/commit for future compatibility.
2. Have the browser load this metadata when opening a timestamp so it can drive future reruns without prompting the user.

## Phase 2 — Support Targeted Reruns in Analyzer
1. Add an optional `--targets-file` CLI argument (JSON list of absolute/relative paths) consumed by `disk_analyzer.py`.
2. When supplied, only analyze the specified paths:
   - Create a new timestamp directory under the same base output.
   - For each path, calculate relative output structure with existing helpers.
   - Reuse saved analyzer flags (min-size, sudo, quiet).
3. Emit a manifest (e.g., `rerun_manifest.json`) into the new run capturing the list of refreshed paths and source run ID.

## Phase 3 — Browser Selection UX
1. Introduce browser state:
   ```python
   self.marked_paths = {}  # path -> {'path': original_path, 'status': 'pending'|'queued'|...}
   self.action_mode = 'browse'  # toggle when entering submit dialog
   ```
2. Handle new keys:
   - `U`: toggle “update” mark for the highlighted directory.
   - `C`: clear all marks (quality-of-life).
   - `S`: open submit/confirm dialog when marks exist.
3. Adjust list rendering:
   - Append tags such as `[U]`, `[running]` to marked entries.
   - Use `curses.init_pair` to color pending/running marks differently.
4. Add a compact status bar summarizing:
   - Count of marked directories.
   - Key hints (`S submit`, `C clear`).
   - Currently highlighted directory’s mark state.

## Phase 4 — Submit Flow
1. On submit confirmation:
   - Validate that all marked directories belong to the current timestamp run.
   - Build a manifest JSON containing selected paths and the source run’s metadata.
   - Write manifest to a temp file under `output/` (e.g., `output/.tmp/browser_submit_<pid>.json`).
2. Tear down curses cleanly (`curses.endwin()`), report the action to stdout, and invoke:
   ```bash
   python3 disk_analyzer.py --output <base-output> --targets-file <manifest>
   ```
   using the root directory and analyzer flags from metadata.
3. Stream analyzer output directly so the user sees progress; on completion, capture the new timestamp directory name.
4. Relaunch the browser automatically on the new timestamp so the user resumes in the refreshed context.

## Phase 5 — Error Handling & UX Polish
- Detect and warn if metadata is missing or incompatible (fall back to prompting for parameters).
- If a rerun fails, display the error after returning to curses and keep the selection state so the user can retry.
- Prevent duplicate marks: disallow marking when a job is already in progress.
- Consider limiting selections to a reasonable number to avoid massive reruns inadvertently.

## Testing & Validation
- Unit-test metadata load/save and the new `--targets-file` pathway (mock filesystem).
- Add integration smoke test that marks two directories, submits, and verifies new run output exists.
- Manual QA: ensure marks persist while navigating parent/child directories and that UI cleans up after rerun.

## Open Questions
- Should parent directories automatically refresh to keep aggregate sizes accurate?
- How should permissions (sudo prompts) be handled during the blocking rerun when triggered from curses?
