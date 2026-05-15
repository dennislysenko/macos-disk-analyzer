# E2E Regression Flows

Step-by-step user-visible flows for the disk-analyzer Opportunity Ladder.
Each flow is a concrete script that can be run by hand (or, eventually,
automated) to verify nothing has regressed. Sibling document to
`SOT.md` — SOT describes *what* the system does; this doc describes
*how to prove it still does it*.

Flows are grouped by feature. Each flow lists:

- **Preconditions**: what state the user/system needs to be in.
- **Steps**: the exact key sequence and observable state.
- **Pass criteria**: what counts as "still working."
- **Rollback**: how to leave the system in its starting state when done.

Convention: `→` means "observe", `⇥` means "press a key".

---

## 1. Opportunity Ladder core

### 1.1 Open the ladder against the latest scan

**Preconditions**: at least one scan exists under the configured
`output_dir` (default `./output/`).

**Steps**:
1. Run `disk-analyzer --latest-recommendations`.
2. → fullscreen ladder, title bar `Opportunity Ladder`.
3. → at least one row, sorted safest/largest first.
4. → footer shows `↑/↓: Nav  t: Sort  r: Rescan  a: AI  m: Review  p: Project  V: Reviewed  P: Projects  x: Trash  q: Back`.
5. ⇥ `q` to exit.

**Pass criteria**: the ladder opens directly without going through the
TUI main menu, and exits cleanly with `q`.

**Rollback**: none (read-only).

### 1.2 Empty-state splash

**Preconditions**: `output_dir` empty (rename it temporarily).

**Steps**:
1. Run `disk-analyzer --latest-recommendations`.
2. → "No scans found" splash.
3. ⇥ any key.

**Pass criteria**: splash renders, exits on keypress, doesn't crash.

**Rollback**: restore `output_dir`.

### 1.3 Trash an item from Active

**Preconditions**: ladder open with at least one disposable row (a
synthetic test row is best — e.g. a deliberately-created
`~/disk-analyzer-test-trash/` with a 200 MB file, scanned).

**Steps**:
1. Navigate to the test row with `↑`/`↓`.
2. ⇥ `x`.
3. → bottom prompt `Move to Trash? <size> <path> (y/n)`.
4. ⇥ `y`.
5. → flash `Moved to Trash.`.
6. → row disappears from ladder.

**Pass criteria**: file lands in `~/.Trash`, row vanishes, snapshot
sizes propagate up correctly (parent rows shrink).

**Rollback**: restore from Trash.

### 1.4 Mark/unmark reviewed

**Steps**:
1. ⇥ `m` on a row in Active → flash `Marked reviewed.`, row disappears.
2. ⇥ `V` → switch to Reviewed view, the row is here.
3. ⇥ `m` on it → flash `Unmarked.`, row disappears.
4. ⇥ `V` → back to Active, the row is here again.

**Pass criteria**: `<scan_dir>/reviewed_paths.json` contains the path
between steps 1 and 3, and is empty after step 3.

### 1.5 Active project walk-up

**Steps**:
1. Find a `node_modules` row.
2. ⇥ `p` → flash `Active project: <parent dir>` (note: the parent, not
   `node_modules` itself).
3. ⇥ `P` → confirm parent appears in Active Projects view.
4. ⇥ `p` to unmark.

**Pass criteria**: `~/.config/disk-analyzer/active_projects.json`
contains the parent directory between steps 2 and 4.

---

## 2. Specialized cleaner: `t` key (registry-backed)

### 2.1 Inline call-to-action and footer hint

**Preconditions**: a scan that included `~/Library/Developer/CoreSimulator`
or `~/Library/Messages/Attachments`.

**Steps**:
1. Open ladder.
2. Navigate to a `CoreSimulator` or `Messages/Attachments` row.
3. → primary line still reads `Review: <rationale>` (unchanged).
4. → path line still shows the shortened path.
5. → a **third** line `▸ Press t to open <label>` is rendered in
   cyan/bold immediately under the path (using the row's normally-blank
   gap line).
6. → footer includes `t: sim_cleanup` (or `t: iMessage runbook`).
7. Move selection to a row without a tool (e.g. a `node_modules` row).
8. → no third line — the gap is back.
9. → `t:` segment is gone from the footer.

**Pass criteria**: tool-bearing rows are visually distinct enough that a
user notices the affordance without reading the footer. The CTA is
additive (does not displace the action label or rationale) and is
**always-on** for tool-bearing rows.

### 2.2 `t` on a row without a tool flashes

**Steps**:
1. Select any row whose rationale doesn't mention a runbook/handoff.
2. ⇥ `t`.
3. → flash `No specialized tool for this row.`.

**Pass criteria**: no crash, no state change.

---

## 3. `sim_cleanup` recipe (kind=tui)

### 3.1 First-time launch on a clean machine triggers install runbook

**Preconditions**: `~/.config/disk-analyzer/preferences.json` does not
contain `tools.sim_cleanup.path`, neither
`~/.local/share/disk-analyzer/tools/sim_cleanup.py` nor
`~/dev/ios-simulator-cleanup/sim_cleanup.py` exists, and
`which sim_cleanup` returns nothing.

**Steps**:
1. Select the `CoreSimulator` row.
2. ⇥ `t`.
3. → fullscreen panel `Install sim_cleanup  (1/2)` opens (this is the
   install runbook, not a launch).
4. → step 1 body explains the managed install location and shows the
   `mkdir … curl … chmod +x` one-liner.
5. ⇥ `r` to run the command in a new Terminal, OR ⇥ `c` to copy and
   paste it into your own shell.
6. After the curl finishes, the panel re-renders (any keypress) and
   the header shows `✓ already done` plus the green
   `✓ sim_cleanup.py available at ~/.local/share/disk-analyzer/tools/sim_cleanup.py`
   banner.
7. ⇥ `n` to step 2; the same ✓ banner is present.
8. ⇥ `q` to close the runbook.
9. → flash `Launched sim_cleanup (~/.local/share/disk-analyzer/tools/sim_cleanup.py).`.
10. → new Terminal.app window opens running the tool's TUI.

**Pass criteria**: a user with nothing pre-installed can go from `t`
press to running sim_cleanup in two keystrokes (`t`, `r`, then `q`).
The managed binary is left on disk for subsequent runs (flow 3.2).

### 3.1.5 Aborting the install runbook leaves the row unchanged

**Steps**:
1. Same preconditions as 3.1.
2. ⇥ `t` → install runbook opens.
3. ⇥ `q` *without* running the install command.
4. → flash `sim_cleanup not installed — aborted.`.
5. → ladder unchanged; row is still tagged with `▸ Press t to open
   sim_cleanup`.

**Pass criteria**: aborting is non-destructive. Re-pressing `t` opens
the install runbook again.

### 3.2 Resolution order for already-installed tool

**Preconditions**: any one of these is true:
- `tools.sim_cleanup.path` is set in preferences.json, OR
- `~/.local/share/disk-analyzer/tools/sim_cleanup.py` exists (managed
  install from flow 3.1), OR
- `~/dev/ios-simulator-cleanup/sim_cleanup.py` exists (dev clone), OR
- `sim_cleanup` is on `$PATH`.

**Steps**:
1. ⇥ `t` on the `CoreSimulator` row.
2. → no install runbook; flash `Launched sim_cleanup (<resolved path>).`.

**Pass criteria**: resolution prefers the user's explicit pref over
managed over dev over PATH. Setting an override in
`preferences.json` always wins.

### 3.3 Live summary shows in rationale

**Preconditions**: `sim_cleanup.py` on disk and at least one simulator
exists locally.

**Steps**:
1. Open ladder. Look at the `CoreSimulator` row's rationale.
2. → text matches `<N> simulators, <SIZE> total — handoff to sim_cleanup`
   instead of the static "iOS Simulator runtimes and device data."

**Pass criteria**: the rationale is *live data*, not a hardcoded string.
If `sim_cleanup.py` is missing, the static rationale is shown
(failure is silent).

### 3.4 Tool failure is non-fatal

**Preconditions**: configure a bogus path (`tools.sim_cleanup.path =
"/nonexistent/sim.py"`).

**Steps**:
1. Restart the ladder.
2. → row still renders with the static rationale (live summary failed
   silently).
3. ⇥ `t` on the row.
4. → flash flow re-prompts for a path.

**Pass criteria**: no exception escapes to the curses loop. Recovery is
self-service.

### 3.5 Sizes refresh after sim_cleanup exits

**Steps**:
1. ⇥ `t` to launch sim_cleanup.
2. In the spawned Terminal, delete a simulator using the tool.
3. Quit sim_cleanup, return to the ladder window.
4. ⇥ `r` on the `CoreSimulator` row.
5. → flash `Rescanned: <new smaller size>`.

**Pass criteria**: ladder picks up the new size; row is not stale.

---

## 4. `imessage_backup` recipe (kind=runbook)

### 4.1 Open the runbook

**Preconditions**: scan included `~/Library/Messages/Attachments`.

**Steps**:
1. Navigate to the row. → footer includes `t: iMessage runbook`.
2. ⇥ `t`.
3. → fullscreen panel: title `iMessage backup → iCloud  (1/6)`.
4. → step 1 body explains brew install.
5. → command line shows `brew install imessage-exporter`.
6. → footer: `n/→: Next  b/←: Prev  c: Copy cmd  r: Run cmd  q/Esc: Back`.

**Pass criteria**: panel renders the right step count and the right
keybindings.

### 4.1.5 Precondition check renders ✓ when satisfied

**Preconditions**: `imessage-exporter` is installed and on `PATH`
(verify with `which imessage-exporter`).

**Steps**:
1. ⇥ `t` on the Attachments row.
2. → step 1 panel renders with `✓ already done` in the header.
3. → green `✓ imessage-exporter is on PATH at <path>` banner under the
   step title.
4. → title is dimmed but body is still visible.
5. ⇥ `n` to advance to step 3 (the export step). If the export folder
   does not yet exist, no ✓ shows. Run the export, then revisit:
   the ✓ now shows on step 3 too.

**Pass criteria**: `check` callables run at render time and are
respected. The pattern works for any future runbook recipe.

### 4.2 Walk all six steps

**Steps**:
1. From step 1: ⇥ `n` 5 times → reach step `(6/6)`.
2. → step 6 says "return to the Opportunity Ladder ... trash the
   highlighted Attachments row with x."
3. ⇥ `n` again → stays on step 6 (no-op).
4. ⇥ `b` 5 times → back at step 1.
5. ⇥ `b` again → stays on step 1 (no-op).
6. → arrows (`←` / `→`) work identically.

**Pass criteria**: navigation is bounded; no off-by-one or wrap.

### 4.3 Copy command to clipboard

**Steps**:
1. On step 1 (or any step with a command):
2. ⇥ `c`.
3. → flash `Command copied to clipboard.`.
4. Switch to a separate terminal, run `pbpaste`.
5. → output is `brew install imessage-exporter`.

**Pass criteria**: pbcopy actually contains the command string. No
trailing newline expected.

### 4.4 Run command in Terminal

**Steps**:
1. On step 1: ⇥ `r`.
2. → flash `Running in Terminal.`.
3. → new Terminal.app window opens running `brew install
   imessage-exporter`.

**Pass criteria**: the spawned Terminal is independent of the
disk-analyzer process; quitting it doesn't affect the ladder.

### 4.5 Open URL on step 2

**Steps**:
1. ⇥ `n` to step 2 (Full Disk Access).
2. → bottom hint: `Press o to open: x-apple.systempreferences:...`.
3. ⇥ `o`.
4. → System Settings opens to Privacy & Security → Full Disk Access.
5. → flash `Opened URL.`.

**Pass criteria**: the URL scheme works; macOS handles the deep link.

### 4.6 Open export folder on step 4

**Steps**:
1. ⇥ `n` until step 4.
2. ⇥ `o`.
3. → Finder opens at `~/Documents/imessage_export` (creating it if
   necessary).
4. → flash `Opened folder.`.

**Pass criteria**: directory is auto-created if missing, then opened.

### 4.7 Return to ladder and trash the row

**Steps**:
1. From any runbook step, ⇥ `q` (or `Esc`).
2. → back at the ladder, same row selected, flash `Runbook closed.`.
3. ⇥ `x`.
4. → prompt `Tagged Review. Move to Trash anyway? (y/n)` (because the
   rule's action is `review`, not `delete` — this warning is intentional;
   make sure the user actually finished the runbook first).
5. ⇥ `n` to back out, since this is a regression test, not a real
   cleanup.

**Pass criteria**: the runbook → ladder → trash handoff is seamless.
The "review" warning fires for the Attachments row.

---

## 5. Cross-cutting: regressions to watch

These are easy to break with seemingly unrelated changes.

### 5.1 `s` (sort toggle) and `t` (tool) are distinct, both lowercase

**Steps**:
1. From any view: ⇥ `s`.
2. → header switches `Sort: Ease` ↔ `Sort: Size`.
3. → selection sticks to the same path across re-sort.
4. ⇥ `t` on a tool-bearing row.
5. → recipe launches (or flashes "No specialized tool" if not tool-bearing).

**Pass criteria**: `s` only sorts, `t` only opens the tool. Neither
requires Shift. No uppercase-letter ladder binds remain for these
actions.

### 5.2 Recipes don't run during scan-time matching when the path is missing

**Preconditions**: scan output includes a *historical* `CoreSimulator`
row whose path no longer exists (e.g. user deleted CoreSimulator after
scanning).

**Steps**:
1. Open ladder.
2. → the row renders without a live summary (falls back to static
   rationale).
3. ⇥ `r` → row is pruned from snapshot.

**Pass criteria**: `recipe.summary()` swallows errors; the ladder
doesn't crash on stale snapshots.

### 5.3 New recipes show up automatically

When a new recipe is registered in `cleanup_tools.py` and a rule
declares `tool="<name>"`:

1. Restart `disk-analyzer`.
2. → footer hint shows `t: <recipe.label>` on matching rows.
3. → no other rule, view, or keybinding behavior changed.

**Pass criteria**: registry is the only file that needs editing for a
new recipe (plus the rule). No `show_recommendations` changes.
