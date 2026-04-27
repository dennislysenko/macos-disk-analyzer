"""Situation-specific cleanup recipes.

A small registry of "tools" that the Opportunity Ladder can hand off to when
a row matches a known cleanup situation (an iOS Simulator dir, an iMessage
attachments dir, etc.). Two recipe kinds today:

- ``tui``: launch an external interactive tool in a new Terminal window.
- ``runbook``: walk the user through a multi-step procedure in a curses panel.
"""

import curses
import json
import os
import shlex
import shutil
import subprocess
import threading
from collections import namedtuple


ToolRecipe = namedtuple(
    "ToolRecipe",
    [
        "name",            # registry key
        "kind",            # "tui" or "runbook"
        "label",           # short label for footer / rationale prefix
        "applies_to",      # callable(path) -> bool. extra gate beyond the rule pattern
        "summary",         # callable(path) -> Optional[str]. live rationale, or None
        "launch",          # callable(stdscr, path, helpers) -> Optional[str] flash msg
        "pref_key",        # preferences.json key holding tool binary path (or None)
        "default_path",    # str default for pref_key (or None)
        "installed_check", # callable() -> str path or None. None ⇒ always considered installed
        "install_steps",   # list[step dict] for setup runbook when not installed
    ],
)
ToolRecipe.__new__.__defaults__ = (None, None)  # installed_check, install_steps


# ── Registry ────────────────────────────────────────────────────────────────

_REGISTRY = {}

# Process-wide cache for recipe.summary() results. Keyed by (recipe_name, path).
# Summaries can be expensive (e.g. sim_cleanup shells out and walks the
# CoreSimulator tree), so we compute once per process and only refresh when
# the user explicitly rescans or invokes the tool.
_SUMMARY_CACHE = {}
_SUMMARY_MISS = object()  # sentinel: cached "no summary available"
_SUMMARY_INFLIGHT = set()  # (recipe_name, path) keys with a worker running
_SUMMARY_LOCK = threading.Lock()


def register(recipe):
    _REGISTRY[recipe.name] = recipe


def get(name):
    return _REGISTRY.get(name)


def all_recipes():
    return dict(_REGISTRY)


def cached_summary(recipe, path):
    """Return recipe.summary(path), memoized.

    On first miss, kicks off a daemon thread to compute the summary and
    returns None immediately. Subsequent calls return the cached value
    once the worker finishes. None means "no summary yet" or "no summary
    available" — callers should fall back to the static rationale either
    way.
    """
    key = (recipe.name, path)
    with _SUMMARY_LOCK:
        if key in _SUMMARY_CACHE:
            cached = _SUMMARY_CACHE[key]
            return None if cached is _SUMMARY_MISS else cached
        if key in _SUMMARY_INFLIGHT:
            return None
        _SUMMARY_INFLIGHT.add(key)

    def _worker():
        try:
            result = recipe.summary(path)
        except Exception:
            result = None
        with _SUMMARY_LOCK:
            _SUMMARY_CACHE[key] = result if result else _SUMMARY_MISS
            _SUMMARY_INFLIGHT.discard(key)

    threading.Thread(target=_worker, daemon=True).start()
    return None


def invalidate_summary(path=None):
    """Drop cached summaries. If path is given, drop only entries for it."""
    with _SUMMARY_LOCK:
        if path is None:
            _SUMMARY_CACHE.clear()
            return
        for key in list(_SUMMARY_CACHE):
            if key[1] == path:
                _SUMMARY_CACHE.pop(key, None)


# ── Shared helpers ──────────────────────────────────────────────────────────

def _resolve_tool_path(recipe, prefs):
    """Return a usable path to the tool's binary, or None."""
    if not recipe.pref_key:
        return None
    tools = prefs.get("tools") or {}
    entry = tools.get(recipe.pref_key) or {}
    path = entry.get("path") or recipe.default_path
    if path and os.path.exists(os.path.expanduser(path)):
        return os.path.expanduser(path)
    return None


def _set_tool_path(prefs, pref_key, path):
    tools = prefs.get("tools") or {}
    tools[pref_key] = {"path": path}
    prefs["tools"] = tools


def _osascript_terminal(command):
    """Open a new Terminal.app window running ``command`` and activate it."""
    osa_escaped = command.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        f'tell application "Terminal" to do script "{osa_escaped}"\n'
        'tell application "Terminal" to activate'
    )
    subprocess.run(["osascript", "-e", script], check=False)


def _prompt_text(stdscr, prompt, default=""):
    """Single-line text prompt at the bottom of the screen. Returns string or None on Esc."""
    height, width = stdscr.getmaxyx()
    curses.curs_set(1)
    try:
        try:
            stdscr.addstr(height - 1, 0, " " * max(0, width - 1))
            stdscr.addstr(height - 1, 0, prompt[: width - 1], curses.A_BOLD)
        except curses.error:
            pass
        stdscr.refresh()
        curses.echo()
        stdscr.nodelay(False)
        try:
            raw = stdscr.getstr(height - 1, min(len(prompt) + 1, width - 1), 512)
        except curses.error:
            raw = b""
        curses.noecho()
        text = raw.decode("utf-8", errors="replace").strip() if raw else ""
        return text or default
    finally:
        curses.curs_set(0)


# ── sim_cleanup recipe ──────────────────────────────────────────────────────

SIM_CLEANUP_MANAGED_DIR = "~/.local/share/disk-analyzer/tools"
SIM_CLEANUP_MANAGED_PATH = f"{SIM_CLEANUP_MANAGED_DIR}/sim_cleanup.py"
SIM_CLEANUP_RAW_URL = (
    "https://raw.githubusercontent.com/dennislysenko/ios-simulator-cleanup/"
    "main/sim_cleanup.py"
)


def _sim_cleanup_resolve():
    """Return a usable path to sim_cleanup.py, or None.

    Resolution order:
      1. preferences.json → tools.sim_cleanup.path (user override)
      2. managed install location (~/.local/share/disk-analyzer/tools/)
      3. legacy / dev clone at ~/dev/ios-simulator-cleanup/
      4. `which sim_cleanup` / `which sim_cleanup.py` on PATH
    """
    prefs = _load_prefs_safely()
    pref_path = ((prefs.get("tools") or {}).get("sim_cleanup") or {}).get("path")
    candidates = []
    if pref_path:
        candidates.append(os.path.expanduser(pref_path))
    candidates.append(os.path.expanduser(SIM_CLEANUP_MANAGED_PATH))
    candidates.append(os.path.expanduser("~/dev/ios-simulator-cleanup/sim_cleanup.py"))
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
        if c and os.path.isfile(c):
            return c  # exists but not executable; the launcher will prefix python3
    for name in ("sim_cleanup", "sim_cleanup.py"):
        on_path = shutil.which(name)
        if on_path:
            return on_path
    return None


def _sim_cleanup_check_installed():
    found = _sim_cleanup_resolve()
    if found:
        return f"sim_cleanup.py available at {found}"
    return None


SIM_CLEANUP_INSTALL_STEPS = [
    {
        "title": "1. Download sim_cleanup.py",
        "body": (
            "sim_cleanup is a single-file Python script (MIT-licensed). The "
            "command below downloads it from the official upstream repo to a "
            f"managed location ({SIM_CLEANUP_MANAGED_PATH}) and makes it "
            "executable. After this step, disk-analyzer will find it "
            "automatically.\n\n"
            "If you'd rather keep it somewhere else, install it manually and "
            "set tools.sim_cleanup.path in "
            "~/.config/disk-analyzer/preferences.json."
        ),
        "command": (
            f"mkdir -p {SIM_CLEANUP_MANAGED_DIR} && "
            f"curl -fsSL -o {SIM_CLEANUP_MANAGED_PATH} {SIM_CLEANUP_RAW_URL} && "
            f"chmod +x {SIM_CLEANUP_MANAGED_PATH}"
        ),
        "check": _sim_cleanup_check_installed,
    },
    {
        "title": "2. You're done — return to the ladder",
        "body": (
            "Press q to close this panel. disk-analyzer will detect "
            "sim_cleanup automatically, and pressing T on the CoreSimulator "
            "row will open it in a new Terminal window."
        ),
        "command": None,
        "check": _sim_cleanup_check_installed,
    },
]


def _sim_applies(path):
    norm = os.path.normpath(path)
    return norm.endswith("/Library/Developer/CoreSimulator")


def _sim_summary(path):
    """Run `sim_cleanup.py scan --json --top 100` and return a one-liner."""
    tool_path = _sim_cleanup_resolve()
    if not tool_path:
        return None
    try:
        result = subprocess.run(
            [tool_path, "scan", "--json", "--top", "100"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
        return None
    devices = data.get("devices", []) if isinstance(data, dict) else []
    globals_info = data.get("globals", {}) if isinstance(data, dict) else {}
    if not devices and not globals_info:
        return None
    device_total = sum(d.get("size_bytes", 0) for d in devices)
    global_total = 0
    if isinstance(globals_info, dict):
        for v in globals_info.values():
            if isinstance(v, dict):
                global_total += v.get("size_bytes", 0) or 0
            elif isinstance(v, (int, float)):
                global_total += int(v)
    total = device_total + global_total
    return f"{len(devices)} simulators, {_format_bytes(total)} total — handoff to sim_cleanup"


def _sim_launch(stdscr, path, helpers):
    tool_path = _sim_cleanup_resolve()
    if not tool_path:
        # Walk the user through installing it. _show_runbook returns when
        # they press q; the install steps each carry a check() that flips
        # ✓ once the file lands.
        _show_runbook(
            stdscr,
            "Install sim_cleanup",
            SIM_CLEANUP_INSTALL_STEPS,
            path,
            helpers,
        )
        # Re-resolve. invalidate the summary cache for this path so the
        # next render picks up live data.
        invalidate_summary(path)
        tool_path = _sim_cleanup_resolve()
        if not tool_path:
            return "sim_cleanup not installed — aborted."

    # If the file isn't executable, fall back to invoking via python3.
    if os.access(tool_path, os.X_OK):
        cmd = shlex.quote(tool_path)
    else:
        cmd = f"python3 {shlex.quote(tool_path)}"
    _osascript_terminal(cmd)
    return f"Launched sim_cleanup ({tool_path})."


register(ToolRecipe(
    name="sim_cleanup",
    kind="tui",
    label="sim_cleanup",
    applies_to=_sim_applies,
    summary=_sim_summary,
    launch=_sim_launch,
    pref_key="sim_cleanup",
    default_path=SIM_CLEANUP_MANAGED_PATH,
    installed_check=_sim_cleanup_check_installed,
    install_steps=SIM_CLEANUP_INSTALL_STEPS,
))


# ── imessage_backup recipe ──────────────────────────────────────────────────

IMESSAGE_DEFAULT_EXPORT = "~/Documents/imessage_export"


def _imessage_applies(path):
    norm = os.path.normpath(path)
    return norm.endswith("/Library/Messages/Attachments")


def _imessage_summary(path):
    """Cheap-ish probe: parent Messages dir size already known via the row.
    Just nudge the user about the runbook so the rationale is action-oriented."""
    return "Backup with imessage-exporter, then enable Messages in iCloud — runbook"


def _check_imessage_exporter_installed():
    found = shutil.which("imessage-exporter")
    return f"imessage-exporter is on PATH at {found}" if found else None


def _check_imessage_export_exists():
    candidate = os.path.expanduser(IMESSAGE_DEFAULT_EXPORT)
    if not os.path.isdir(candidate):
        return None
    # Strong signal: an HTML index file in the root of the export dir.
    for entry in os.listdir(candidate):
        if entry.endswith(".html"):
            return f"Export folder exists with HTML output at {IMESSAGE_DEFAULT_EXPORT}"
    return None


IMESSAGE_STEPS = [
    {
        "title": "1. Install imessage-exporter",
        "body": (
            "Homebrew is the simplest install. If you don't have Homebrew, "
            "install it from https://brew.sh first.\n\n"
            "If you prefer cargo, run: cargo install imessage-exporter"
        ),
        "command": "brew install imessage-exporter",
        "check": _check_imessage_exporter_installed,
    },
    {
        "title": "2. Grant Full Disk Access to your Terminal",
        "body": (
            "imessage-exporter reads ~/Library/Messages/chat.db, which macOS "
            "protects. Open System Settings → Privacy & Security → Full Disk "
            "Access and enable your terminal app. You may need to restart "
            "the terminal afterwards."
        ),
        "command": None,
        "open_url": "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
    },
    {
        "title": "3. Export your messages to HTML + attachments",
        "body": (
            f"This writes the full archive to {IMESSAGE_DEFAULT_EXPORT}. "
            "If you have lots of attachments, point this at an external drive "
            "instead — otherwise you've moved the bytes 6 inches sideways. "
            "Run the command in a normal terminal (NOT the disk-analyzer "
            "session) so you can see progress."
        ),
        "command": (
            f"imessage-exporter -f html -c full -o "
            f"{IMESSAGE_DEFAULT_EXPORT}"
        ),
        "check": _check_imessage_export_exists,
    },
    {
        "title": "4. Verify the export",
        "body": (
            "Open the export folder and spot-check a recent conversation. "
            "Look for index.html and the attachments/ subfolder. If anything "
            "looks wrong, do NOT proceed to the next step — re-run the "
            "export instead."
        ),
        "command": None,
        "open_path": IMESSAGE_DEFAULT_EXPORT,
    },
    {
        "title": "5. Enable Messages in iCloud",
        "body": (
            "Open Messages → Settings → iCloud and turn on \"Messages in "
            "iCloud\". Wait for the initial sync to finish (status text "
            "stops moving). This frees the local copy to be evicted safely.\n\n"
            "If iCloud storage is full, this step will silently fail to "
            "sync — check iCloud → Manage Storage first."
        ),
        "command": "open -a Messages",
    },
    {
        "title": "6. Reclaim the local Attachments dir",
        "body": (
            "Once iCloud sync has settled, return to the Opportunity Ladder "
            "(press q here) and trash the highlighted Attachments row with "
            "x. The data lives in iCloud and your export folder; macOS will "
            "lazily re-fetch what you actually open later."
        ),
        "command": None,
    },
]


def _imessage_launch(stdscr, path, helpers):
    return _show_runbook(stdscr, "iMessage backup → iCloud", IMESSAGE_STEPS, path, helpers)


register(ToolRecipe(
    name="imessage_backup",
    kind="runbook",
    label="iMessage runbook",
    applies_to=_imessage_applies,
    summary=_imessage_summary,
    launch=_imessage_launch,
    pref_key=None,
    default_path=None,
    installed_check=None,
    install_steps=None,
))


# ── Runbook renderer ────────────────────────────────────────────────────────

def _show_runbook(stdscr, title, steps, path, helpers):
    """Fullscreen panel walking through a list of steps.

    Keys:
      n / →  next step
      b / ←  prev step
      c      copy current step's command to clipboard (pbcopy)
      r      run current step's command in a new Terminal
      o      open the step's url/path in Finder/browser
      q / Esc  back to ladder
    """
    idx = 0
    # Try to set a "done" color pair; safe no-op if curses isn't initialized
    # the way we expect it to be.
    try:
        curses.init_pair(30, curses.COLOR_GREEN, -1)
        done_color = curses.color_pair(30)
    except curses.error:
        done_color = curses.A_BOLD
    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        step = steps[idx]
        check_fn = step.get("check")
        done_msg = None
        if check_fn:
            try:
                done_msg = check_fn()
            except Exception:
                done_msg = None
        try:
            header = f"{title}  ({idx + 1}/{len(steps)})"
            if done_msg:
                header += "  ✓ already done"
            stdscr.addstr(0, 1, header, curses.A_BOLD)
            stdscr.addstr(1, 1, "=" * min(width - 2, 72))
            title_attr = curses.A_BOLD | curses.A_UNDERLINE
            if done_msg:
                title_attr = curses.A_BOLD | curses.A_DIM
            stdscr.addstr(3, 1, step["title"], title_attr)
            if done_msg:
                stdscr.addstr(4, 1, f"✓ {done_msg}", done_color | curses.A_BOLD)
        except curses.error:
            pass

        body_start = 6 if done_msg else 5
        body_lines = _wrap(step["body"], max(20, width - 4))
        y = body_start
        for line in body_lines:
            if y >= height - 7:
                break
            try:
                stdscr.addstr(y, 2, line)
            except curses.error:
                pass
            y += 1

        cmd = step.get("command")
        if cmd:
            try:
                stdscr.addstr(y + 1, 2, "Command:", curses.A_BOLD)
                stdscr.addstr(y + 2, 4, cmd[: max(10, width - 6)], curses.A_DIM)
            except curses.error:
                pass
            y += 3

        url = step.get("open_url")
        target_path = step.get("open_path")
        if url or target_path:
            hint = url or target_path
            try:
                stdscr.addstr(y + 1, 2, f"Press o to open: {hint}"[: width - 3], curses.A_DIM)
            except curses.error:
                pass

        try:
            footer_y = height - 2
            footer = (
                "  n/→: Next  b/←: Prev  "
                + ("c: Copy cmd  r: Run cmd  " if cmd else "")
                + ("o: Open  " if (url or target_path) else "")
                + "q/Esc: Back"
            )
            stdscr.addstr(footer_y, 0, "─" * min(width - 1, 72))
            stdscr.addstr(footer_y + 1 if footer_y + 1 < height else footer_y, 1, footer[: width - 2], curses.A_BOLD)
        except curses.error:
            pass

        stdscr.refresh()
        stdscr.nodelay(False)
        key = stdscr.getch()
        if key in (ord("q"), 27):
            return "Runbook closed."
        if key in (ord("n"), curses.KEY_RIGHT):
            if idx < len(steps) - 1:
                idx += 1
        elif key in (ord("b"), curses.KEY_LEFT):
            if idx > 0:
                idx -= 1
        elif key == ord("c") and cmd:
            try:
                proc = subprocess.run(
                    ["pbcopy"], input=cmd.encode("utf-8"), check=False, timeout=5
                )
                if proc.returncode == 0:
                    helpers["flash"]("Command copied to clipboard.")
                else:
                    helpers["flash"]("pbcopy failed.")
            except (subprocess.SubprocessError, OSError) as exc:
                helpers["flash"](f"Copy failed: {exc}")
        elif key == ord("r") and cmd:
            _osascript_terminal(cmd)
            helpers["flash"]("Running in Terminal.")
        elif key == ord("o"):
            if url:
                subprocess.run(["open", url], check=False)
                helpers["flash"]("Opened URL.")
            elif target_path:
                expanded = os.path.expanduser(target_path)
                os.makedirs(expanded, exist_ok=True)
                subprocess.run(["open", expanded], check=False)
                helpers["flash"]("Opened folder.")
        elif key == curses.KEY_RESIZE:
            pass


def _wrap(text, width):
    """Word-wrap respecting explicit \\n. Returns a list of lines."""
    out = []
    for paragraph in text.split("\n"):
        if not paragraph:
            out.append("")
            continue
        line = ""
        for word in paragraph.split(" "):
            if not line:
                line = word
                continue
            if len(line) + 1 + len(word) <= width:
                line = line + " " + word
            else:
                out.append(line)
                line = word
        if line:
            out.append(line)
    return out


# ── Lookups ────────────────────────────────────────────────────────────────

def find_for_path(path):
    """Return the first registered recipe whose applies_to matches ``path``, or None."""
    for recipe in _REGISTRY.values():
        try:
            if recipe.applies_to(path):
                return recipe
        except Exception:
            continue
    return None


# ── Late imports to avoid circulars ────────────────────────────────────────

def _format_bytes(n):
    from disk_analyzer import _format_bytes as fb
    return fb(n)


def _load_prefs_safely():
    try:
        from cleanup_recommendations import _load_preferences
        return _load_preferences()
    except Exception:
        return {}
