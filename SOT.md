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
| `r`   | Rescan this row asynchronously (background mutation worker; UI stays responsive). If the path is gone → prune from snapshot. If present → re-measure with `du -sk` and propagate updated sizes up the scan tree. While in flight the row's primary line reads `Rescanning…`; on completion the ladder rebuilds. Pressing `r` again on an already in-flight row flashes "Mutation already in flight for this row." |
| `m`   | Mark this row reviewed (per-scan; filters it out of Active view).      |
| `p`   | Mark as an active project (global). For `node_modules` and `venv`/`.venv`/`env`/`.env` rows, walks up to the parent project dir; other paths are marked as-is. |
| `a`   | AI-analyze. Venv rows only. Prompts for agent (Claude / Codex) on first use, optionally remembers the choice, then launches a new Terminal.app window `cd`'d into the venv's parent with a hardcoded prompt asking the agent to sync `requirements.txt` and write a `.python-version`. Non-venv rows flash "AI-analyze only supports Python venvs right now." |
| `T`   | Open the row's specialized cleaner (see §3.4). Active only on rows whose rule declares a `tool`; flashes "No specialized tool for this row." otherwise. Footer dynamically advertises the tool name when one is available for the selected row. After the tool exits, the ladder rebuilds so updated sizes / disappeared rows are reflected. |

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

Other notable rule shapes:
- `*/Applications/*.app` — installed app bundles (medium risk,
  reviewable). `fnmatch`'s `*` matches `/` so both `/Applications/Foo.app`
  and `/Applications/Foo/Foo.app` are picked up; parent-collapses-children
  dedup keeps the bundle path as the row, not its internals.
- `*.photoslibrary` — Photos library bundle, paired with the
  `photos_cleanup` runbook recipe. Critical that we never `delete` the
  bundle — the runbook walks the user through in-app management.
- `*.logicx` — Logic Pro project bundle, high-risk human data.
- WhatsApp media at `*/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/Message/Media`
  paired with `whatsapp_cleanup` runbook.

### 1.4a Unknown big chunks

After the rule-matching pass, `generate_recommendations` does a second
sweep over `_load_seen_paths` for directories ≥ `UNKNOWN_MIN_BYTES`
(1 GB) that no rule matched. These surface as rows with
`risk="unknown"`, `tier="unknown_chunk"`, action `review`, and
rationale "Unclassified large directory — no matching rule" (magenta in
the ladder).

Filtering:
- Drops the scan root itself.
- Drops paths inside `UNKNOWN_EXCLUDED_PREFIXES` (`/private`, `/opt`,
  `/var`, `/System`, `/usr`, `/Library` (system), `/bin`, `/sbin`,
  `/cores`, `/Volumes`) — macOS / OS-managed territory.
- Drops paths *inside* a macOS file-package bundle (any ancestor
  ending in `PACKAGE_EXTENSIONS`: `.app`, `.photoslibrary`, `.logicx`,
  `.framework`, etc.). The bundle path itself is still eligible; its
  internals are not. So `Photos Library.photoslibrary` surfaces as one
  24 GB row instead of four fragmented database/derivatives rows.
- Drops anything overlapping a rule-matched accepted path in *either
  direction*, so sizes don't double-count.
- Respects active-projects and reviewed filters identically to the
  rule-matched pass.

**Dedup is leaf-wins** for unknowns (opposite of the parent-wins
behavior used for rule-matched buckets). Rationale: a rule-matched
parent like `~/Library/Caches` is a single semantic unit you act on
once, whereas an unknown parent is just a sum of unrelated children —
so the natural rule for unknowns is "show the deepest qualifying
chunk." Implementation: sort by path length descending, accept iff no
already-accepted path is a strict descendant. So if both
`/Applications` and `/Applications/Xcode.app` qualify, only Xcode.app
keeps its row.

`RISK_ORDER["unknown"] = 4` (above `high`), so in ladder sort
(`safest/largest first`) unknowns sink to the bottom — exhaust the
vouched-for opportunities first, then triage the mystery pile. In size
sort they interleave with known rows by raw `-size_bytes`, which is the
primary use case: see every big bite regardless of classification.
Unknown rows are actionable via the standard `x` / `m` / `p` / `o`
keys; `a` AI-analyze and `T` tool keys are no-ops (no tool wired).

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
6. Background mutation worker (single daemon thread, lazy-started on
   first `x` or `r`) serializes both **trash** and **rescan** jobs so
   the disk_usage.txt rewrites don't race each other. Jobs are tagged
   tuples `("trash" | "rescan", path)` on `mutation_queue`; results
   `(kind, path, ok, msg)` on `mutation_results`. The main loop drains
   results each tick, dispatches by kind, then rebuilds rows once if
   any rescan completed (sizes may have shifted). While anything is
   in-flight the loop arms a 300 ms `stdscr.timeout()` so the UI
   redraws even without keypresses; per-row primary text shows
   `Trashing…` / `Rescanning…` accordingly. Sticky `trash_failed` /
   `rescan_failed` badges clear on the next real keypress.

### 3.3 Agent launcher (`_launch_ai_agent_for_venv`)

Opens Terminal.app via `osascript` with `cd <parent> && <agent> '<prompt>'`.
The prompt (`VENV_AI_PROMPT`) is hardcoded for venv sync. The agent choice
lives in `preferences.json` under `ai_agent` (`claude` or `codex`); absence
means "ask every time". Conceptually this is a `kind="agent"` recipe; it
predates the registry in §3.4 and has not been folded in yet.

### 3.4 Specialized cleaner registry (`cleanup_tools.py`)

A small registry of "situation-specific" recipes that the ladder hands off
to when a row matches a known cleanup situation. Two kinds today:

- `kind="tui"` — launch an external interactive tool in a new Terminal
  window. Example: `sim_cleanup`. Resolution order:
  (1) `preferences.json → tools.sim_cleanup.path`,
  (2) managed install at `~/.local/share/disk-analyzer/tools/sim_cleanup.py`,
  (3) dev clone at `~/dev/ios-simulator-cleanup/sim_cleanup.py`,
  (4) `which sim_cleanup` / `which sim_cleanup.py`.
  When none resolve, the recipe shows an install runbook before
  launching (see "self-installing recipes" below).
- `kind="runbook"` — walk the user through a multi-step procedure in a
  curses panel. Example: `imessage_backup` (install
  `imessage-exporter`, grant Full Disk Access, run the export, enable
  Messages in iCloud, return to the ladder to trash the local copy).

Recipes carry two optional setup fields that turn a TUI recipe into a
self-installing one:

- `installed_check()` — returns a non-empty string when the tool is
  ready to run, else `None`. Used both by the install runbook's per-
  step `check` (so the ✓ flips when the install lands) and by the
  recipe's own `launch` to gate execution.
- `install_steps` — same shape as runbook steps. Rendered via
  `_show_runbook` whenever `launch` discovers the tool is missing.
  After the user closes the install panel, `launch` re-resolves the
  binary and either proceeds or flashes "tool not installed — aborted."

For sim_cleanup the install step downloads the upstream raw URL
(`https://raw.githubusercontent.com/dennislysenko/ios-simulator-cleanup/main/sim_cleanup.py`)
into the managed location and `chmod +x`'s it. No vendoring; upstream
is a single-file MIT-licensed script.

Wiring path:

1. A `CleanupRule` declares `tool="<recipe_name>"` (last positional arg,
   defaults to `None`). Example rules: `*/Library/Developer/CoreSimulator`
   → `sim_cleanup`; `*/Library/Messages/Attachments` →
   `imessage_backup`.
2. `generate_recommendations` looks the recipe up in `cleanup_tools`
   and confirms `recipe.applies_to(path)` is true (extra gate beyond
   the pattern). The live summary is **not** computed here — that
   would block initial paint on slow probes (sim_cleanup walks the
   CoreSimulator tree and takes several seconds). Instead, the static
   rule rationale is used.
3. Render time, for tool-bearing rows, the renderer calls
   `cleanup_tools.cached_summary(recipe, path)`. The first call kicks
   off a daemon thread to compute `recipe.summary(path)` and returns
   `None` immediately; subsequent calls return the cached result.
   When the worker finishes, the next render (any keystroke triggers
   one) swaps the static rationale for the live one (e.g. "5
   simulators, 24 GB total — handoff to sim_cleanup"). Failures are
   swallowed; the static rationale stays. `r` rescan and `T` launch
   both invalidate the row's cache entry so the next render re-probes.
4. The recipe name is threaded through `Recommendation.tool`. Tool-
   bearing rows keep the standard `Action: rationale` primary line and
   add a third line `▸ Press T to open <recipe.label>` in cyan/bold
   (the line that's normally a blank gap between rows). Rows without a
   tool keep the blank gap. The footer also advertises
   `T: <recipe.label>` for the selected row.
5. On `T`, `show_recommendations` calls
   `recipe.launch(stdscr, path, helpers)`. The `helpers` dict gives the
   recipe `load_prefs`, `save_prefs`, and `flash` so it can prompt for /
   persist tool paths and surface status without owning curses
   primitives. Return value is a flash message (or `None`).
6. After `launch` returns, the ladder is rebuilt unconditionally so
   sizes settle from any underlying mutation.

Runbook UI (`cleanup_tools._show_runbook`): one step on screen at a
time. Each step has `title`, `body`, optional `command`, optional
`open_url` / `open_path`, optional `check`. The `check` callable is
invoked at render time and, when it returns a truthy string, the step
renders with a green `✓ already done` banner and dims the title (the
body still shows so the user can re-run if they want). General pattern:
recipes use `check` to detect already-satisfied preconditions
(`shutil.which("imessage-exporter")`, "export folder exists", etc.) so
the runbook is honest about what's left to do.

Keys: `n`/`→` next, `b`/`←` back, `c` copies the current command to the
clipboard via `pbcopy`, `r` runs the command in a new Terminal window,
`o` opens the URL/path, `q`/`Esc` returns to the ladder.

Adding a new recipe is a four-step exercise: write `applies_to` /
`summary` / `launch`, call `cleanup_tools.register(...)` at import time,
add a `tool="..."` to the matching `CleanupRule`, and document the
flow in `E2E_FLOWS.md`.

---

## 4. TODO: modules not yet covered

- `disk_analyzer.py` — parallel scan worker, `AnalysisStats`, `run_analysis`. Document walk strategy, min-size cutoff semantics, worker pool, stats fan-in, output layout.
- `disk_analyzer_cli.py` — TUI main menu, scan setup wizard, progress UI, ETA heuristic (`estimate_from_history` / `save_scan_history`).
- `browser_tui.py` — directory browser, timestamp selector, per-directory drill-down, in-browser trash actions.
- `browser_gui.py` — matplotlib/tkinter GUI counterpart. Document feature parity (or lack of) vs the TUI.
- Scan output layout — what exactly is written to `<scan_dir>/`, invariants on the mirrored tree, how `format_path_for_output` maps filesystem paths to snapshot paths.
