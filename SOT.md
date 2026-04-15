# Source of Truth

Living description of what the app does and how the pieces fit together.
User-facing flows for the Opportunity Ladder are covered exhaustively;
other modules are stubbed with TODOs and will be filled in as we
formalize them.

---

## 1. Top-level user stories

### 1.1 Jump straight to the ladder for the latest scan

```
disk-analyzer --latest-recommendations
```

Short-circuits past the TUI main menu and the scan picker. Loads the
newest timestamp directory under the configured output dir (default
`./output/`) and opens the Opportunity Ladder against it. If no scans
exist, shows a "No scans found" splash and exits on keypress.

Code: `disk_analyzer_cli.run_latest_recommendations` →
`cleanup_recommendations.generate_recommendations` →
`cleanup_recommendations.show_recommendations`.

### 1.2 Walk the ladder, curate what to delete

The Opportunity Ladder is a fullscreen curses view. Each row is a
candidate cleanup target: a path, a size, a risk color, a tier label,
and a one-line rationale. Rows are sorted safest/largest first by
default; `t` flips to pure size-descending.

Three views share the same chrome, toggled by uppercase keys:

| View             | Toggle | What you see                                            |
|------------------|--------|---------------------------------------------------------|
| Active (default) | —      | Live recommendations (not reviewed, not in an active project) |
| Reviewed         | `V`    | Rows you've hit `m` on this scan                        |
| Active Projects  | `P`    | Globally-pinned project roots (excluded everywhere)     |

`V` and `P` are idempotent toggles: pressing either from its own view
returns to Active.

### 1.3 Keybindings

All bindings are case-sensitive.

#### Navigation

| Key                 | Action                             |
|---------------------|------------------------------------|
| `↑` / `↓`           | Move selection                     |
| `fn+↑` / `fn+↓`     | PageUp/PageDown (one page at a time) |
| `t`                 | Toggle sort: ladder ↔ size-descending |
| `q` / `Esc`         | Back to caller                     |

#### Per-row actions (Active view)

| Key   | Action                                                                 |
|-------|------------------------------------------------------------------------|
| `x`   | Move to Trash. Confirms y/n. On success prunes the row from the scan snapshot. If the path is already gone, prunes the stale snapshot entry instead of just erroring. |
| `o`   | Open the path in Finder.                                               |
| `r`   | Rescan this row. If the path is gone → prune from snapshot. If present → re-measure with `du -sk` and propagate updated sizes up the scan tree. |
| `m`   | Mark this row reviewed (per-scan; filters it out of Active view).      |
| `p`   | Mark as an active project (global). For `node_modules` and `venv`/`.venv`/`env`/`.env` rows, walks up to the parent project dir; other paths are marked as-is. |
| `a`   | AI-analyze. Venv rows only. Prompts for agent (Claude / Codex) on first use, optionally remembers the choice, then launches a new Terminal.app window `cd`'d into the venv's parent with a hardcoded prompt asking the agent to sync `requirements.txt` and write a `.python-version`. Non-venv rows flash "AI-analyze only supports Python venvs right now." |

#### Per-row actions (Reviewed view)

| Key   | Action                                       |
|-------|----------------------------------------------|
| `m`   | Unmark (moves the row back to Active).       |
| `x`   | Trash the reviewed row (same flow as Active). |
| `p`   | Promote to active project (walks up if venv/node_modules). |
| Others | Same semantics as Active where meaningful.  |

#### Per-row actions (Active Projects view)

| Key   | Action                       |
|-------|------------------------------|
| `p`   | Unmark the active project.   |
| `o`   | Open in Finder.              |

Other actions are no-ops or skipped; these rows are synthetic and don't
live in the scan snapshot.

### 1.4 Risk tuning based on sibling files

Rule-matched rows have their risk re-graded at render time based on
what's next to them in the filesystem:

- **`node_modules`**
  - Sibling `package-lock.json` / `yarn.lock` / `pnpm-lock.yaml` / `bun.lock*` → **safe**, rationale mentions the lockfile name.
  - No lockfile → **medium** risk + **Review First** tier, rationale "no lockfile in parent, review before deleting".
- **`venv` / `.venv` / `env` / `.env`** (or any dir containing `pyvenv.cfg`)
  - Sibling lockfile (`uv.lock` / `poetry.lock` / `Pipfile.lock`) → **safe**, "restorable exactly".
  - Sibling manifest only (`requirements.txt` / `pyproject.toml` / `Pipfile`) → rule default (low risk).
  - Neither → **medium** + **Review First**.

Lock vs manifest split lives in `VENV_LOCKFILES` / `VENV_MANIFESTS`
constants and `_venv_dependency_file`.

### 1.5 Active projects

Global (not per-scan) allowlist of project roots that should never
surface in the ladder. Walk-up logic on `p`:

- `foo/node_modules` → marks `foo`
- `foo/.venv` → marks `foo`
- Anything else → marks the exact selected path

Once marked, `_is_under_active_project` filters the whole subtree out
of both Active and Reviewed views. They only appear in the Active
Projects view (`P`).

Persisted to `~/.config/disk-analyzer/active_projects.json` as a
sorted JSON list.

### 1.6 Reviewed items

Per-scan "I looked at this, ignore it for now" marker. Stored at
`<scan_dir>/reviewed_paths.json`. A fresh scan starts empty because
sizes and contents change.

---

## 2. Storage / on-disk surface

| Path                                              | Scope      | Lifetime  | Writer                       |
|---------------------------------------------------|------------|-----------|------------------------------|
| `<output_dir>/<timestamp>/`                       | per scan   | until deleted | scan writer (TODO)       |
| `<scan_dir>/disk_usage.txt`                       | per scan   | per scan  | scan writer (TODO)           |
| `<scan_dir>/<rel-path>/disk_usage.txt`            | per scan   | per scan  | scan writer (TODO)           |
| `<scan_dir>/reviewed_paths.json`                  | per scan   | per scan  | `_save_reviewed_paths`       |
| `~/.config/disk-analyzer/config.toml`             | user-wide  | manual    | user                         |
| `~/.config/disk-analyzer/preferences.json`        | user-wide  | permanent | `_save_preferences`          |
| `~/.config/disk-analyzer/active_projects.json`    | user-wide  | permanent | `_save_active_projects`      |
| `<output_dir>/.scan_history.json`                 | user-wide  | last 20   | `save_scan_history`          |

---

## 3. Shared logic (architectural notes only)

This section documents load-bearing non-user-facing helpers. It is
deliberately incomplete; fill in as modules get formalized.

### 3.1 `file_actions.py`

Trash / snapshot mutation layer. All functions operate on the mirrored
scan snapshot (the `disk_usage.txt` tree under `<scan_dir>`) and never
mutate the live filesystem except `move_path_to_trash`.

- `move_path_to_trash(path)` — moves to `~/.Trash`, returns destination. Handles name collisions with a numeric suffix.
- `remove_path_from_scan(scan_dir, root_path, target_path)` — removes the entry from its parent's `disk_usage.txt`, propagates aggregate size updates all the way to the scan root, and `rmtree`s the mirrored subtree. Refuses to operate on the scan root itself.
- `update_path_size_in_scan(scan_dir, root_path, target_path, new_size_bytes)` — same propagation as above but rewrites the size instead of removing the entry. The mirrored subtree is left untouched.
- `measure_path_size_bytes(path)` — current on-disk size. `os.path.getsize` for files/links, `du -sk` for directories. Returns 0 on any failure.

Invariant: `remove_path_from_scan` and `update_path_size_in_scan` both
walk child → parent → ... → root, rewriting each parent's
`disk_usage.txt` so aggregate sizes stay consistent across the whole
snapshot. The snapshot is what the Browser and the Ladder both read
from; if it drifts from reality the user sees stale sizes.

### 3.2 `cleanup_recommendations.py` pipeline

1. `_load_seen_paths(scan_dir)` → `{path: (size_bytes, size_str)}` flattens every mirrored `disk_usage.txt`.
2. `generate_recommendations(scan_dir, root_path, only_reviewed=False)`:
   - Filters out paths under any active project.
   - Filters reviewed-in-or-out based on `only_reviewed`.
   - Matches remaining paths against `CLEANUP_RULES` via `fnmatch`, first match wins.
   - Risk/tier/rationale are re-graded in-place for `node_modules` and venvs (see §1.4).
   - Deduplicates: keeps parents over children for same-rule matches.
   - Sorts by `_sort_key` (risk → -size → tier → path), caps at `MAX_RECOMMENDATIONS`.
3. `_sort_recommendations` re-sorts for the UI toggle (`SORT_LADDER` vs `SORT_SIZE`).
4. `_build_rows` wraps Recommendations for the curses renderer. `_build_active_project_recommendations` synthesizes rows for the Active Projects view from the global set (size looked up from the current scan's `_load_seen_paths` if present, else "—").
5. `show_recommendations` owns the keybind loop. The local `rebuild_rows(sort, view)` closure re-derives `(recommendations, ordered, rows)` from scratch whenever mutation happens, so we never have to reason about partial updates.

### 3.3 Agent launcher (`_launch_ai_agent_for_venv`)

Opens Terminal.app via `osascript` with `cd <parent> && <agent> '<prompt>'`.
The prompt (`VENV_AI_PROMPT`) is hardcoded for venv sync; we'll
generalize when a second use case lands. The agent choice lives in
`preferences.json` under `ai_agent` (`claude` or `codex`); absence
means "ask every time".

---

## 4. TODO: modules not yet covered

- `disk_analyzer.py` — parallel scan worker, `AnalysisStats`, `run_analysis`. Document walk strategy, min-size cutoff semantics, worker pool, stats fan-in, output layout.
- `disk_analyzer_cli.py` — TUI main menu, scan setup wizard, progress UI, ETA heuristic (`estimate_from_history` / `save_scan_history`).
- `browser_tui.py` — directory browser, timestamp selector, per-directory drill-down, in-browser trash actions.
- `browser_gui.py` — matplotlib/tkinter GUI counterpart. Document feature parity (or lack of) vs the TUI.
- Scan output layout — what exactly is written to `<scan_dir>/`, invariants on the mirrored tree, how `format_path_for_output` maps filesystem paths to snapshot paths.
