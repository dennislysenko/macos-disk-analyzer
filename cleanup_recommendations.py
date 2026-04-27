"""Cleanup recommendation engine for disk-analyzer.

Scans analysis output for known cleanup opportunities and ranks them as an
"opportunity ladder": safest, largest, and most reversible items first.
"""

import curses
import fnmatch
import json
import os
import subprocess
from collections import namedtuple

REVIEWED_FILE = "reviewed_paths.json"


def _reviewed_file_path(scan_dir):
    return os.path.join(scan_dir, REVIEWED_FILE)


def _load_reviewed_paths(scan_dir):
    if not scan_dir:
        return set()
    path = _reviewed_file_path(scan_dir)
    if not os.path.exists(path):
        return set()
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, list):
            return set(data)
    except (OSError, json.JSONDecodeError):
        pass
    return set()


def _save_reviewed_paths(scan_dir, reviewed):
    if not scan_dir:
        return
    path = _reviewed_file_path(scan_dir)
    with open(path, "w") as f:
        json.dump(sorted(reviewed), f, indent=2)


PREFERENCES_DIR = os.path.expanduser("~/.config/disk-analyzer")
PREFERENCES_FILE = os.path.join(PREFERENCES_DIR, "preferences.json")
ACTIVE_PROJECTS_FILE = os.path.join(PREFERENCES_DIR, "active_projects.json")


def _load_active_projects():
    if not os.path.exists(ACTIVE_PROJECTS_FILE):
        return set()
    try:
        with open(ACTIVE_PROJECTS_FILE) as f:
            data = json.load(f)
        if isinstance(data, list):
            return {os.path.normpath(p) for p in data}
    except (OSError, json.JSONDecodeError):
        pass
    return set()


def _save_active_projects(projects):
    os.makedirs(PREFERENCES_DIR, exist_ok=True)
    with open(ACTIVE_PROJECTS_FILE, "w") as f:
        json.dump(sorted(projects), f, indent=2)


def _is_under_active_project(path, active_projects):
    norm = os.path.normpath(path)
    for root in active_projects:
        if norm == root or norm.startswith(root + os.sep):
            return True
    return False


def _active_project_root_for_path(path):
    """For venv/node_modules rows, return the parent project dir. Otherwise return the path as-is."""
    norm = os.path.normpath(path)
    base = os.path.basename(norm)
    if base == "node_modules" or base in {"venv", ".venv", "env", ".env"}:
        parent = os.path.dirname(norm)
        return parent or norm
    return norm

VENV_AI_PROMPT = (
    "please see if requirements.txt reflects the venv packages; if not, "
    "please make it so. and make a .python-version with the python version "
    "from the venv."
)

AI_AGENTS = {
    "claude": "claude",
    "codex": "codex",
}


def _load_preferences():
    if not os.path.exists(PREFERENCES_FILE):
        return {}
    try:
        with open(PREFERENCES_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_preferences(prefs):
    os.makedirs(PREFERENCES_DIR, exist_ok=True)
    with open(PREFERENCES_FILE, "w") as f:
        json.dump(prefs, f, indent=2)


def _node_modules_lockfile(node_modules_path):
    """Return the path of a sibling lockfile if one exists, else None."""
    parent = os.path.dirname(os.path.normpath(node_modules_path))
    for name in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock"):
        candidate = os.path.join(parent, name)
        if os.path.isfile(candidate):
            return candidate
    return None


VENV_LOCKFILES = ("uv.lock", "poetry.lock", "Pipfile.lock")
VENV_MANIFESTS = ("requirements.txt", "pyproject.toml", "Pipfile")


def _venv_dependency_file(venv_path):
    """Return (path, is_lockfile) for the strongest dep descriptor in the parent.

    Lockfiles beat manifests; returns (None, False) if nothing is found.
    """
    parent = os.path.dirname(os.path.normpath(venv_path))
    for name in VENV_LOCKFILES:
        candidate = os.path.join(parent, name)
        if os.path.isfile(candidate):
            return candidate, True
    for name in VENV_MANIFESTS:
        candidate = os.path.join(parent, name)
        if os.path.isfile(candidate):
            return candidate, False
    return None, False


def _looks_like_venv(path):
    base = os.path.basename(os.path.normpath(path))
    if base in {"venv", ".venv", "env", ".env"}:
        return True
    if os.path.isfile(os.path.join(path, "pyvenv.cfg")):
        return True
    return False


def _launch_ai_agent_for_venv(agent, venv_path):
    """Open a new Terminal.app window in the venv's parent and run the agent."""
    import shlex

    project_dir = os.path.dirname(os.path.normpath(venv_path)) or "/"
    cmd = AI_AGENTS.get(agent, agent)
    full_cmd = f"cd {shlex.quote(project_dir)} && {cmd} {shlex.quote(VENV_AI_PROMPT)}"
    osa_escaped = full_cmd.replace("\\", "\\\\").replace('"', '\\"')
    script = f'tell application "Terminal" to do script "{osa_escaped}"\n'
    script += 'tell application "Terminal" to activate'
    subprocess.run(["osascript", "-e", script], check=False)

from disk_analyzer import parse_size, _format_bytes
from file_actions import (
    measure_path_size_bytes,
    move_path_to_trash,
    remove_path_from_scan,
    update_path_size_in_scan,
)
import cleanup_tools

CleanupRule = namedtuple(
    "CleanupRule",
    [
        "pattern",
        "category",
        "tier",
        "risk",
        "action",
        "rationale",
        "regeneration",
        "tool",
    ],
)
CleanupRule.__new__.__defaults__ = (None,)  # tool is optional

Recommendation = namedtuple(
    "Recommendation",
    [
        "path",
        "size_bytes",
        "size_human",
        "category",
        "tier",
        "risk",
        "action",
        "rationale",
        "regeneration",
        "tool",
    ],
)
Recommendation.__new__.__defaults__ = (None,)

TIER_ORDER = {
    "purge_now": 0,
    "rebuildable_dev": 1,
    "reviewable_state": 2,
    "human_data": 3,
}

RISK_ORDER = {
    "safe": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}

TIER_LABELS = {
    "purge_now": "Purge Now",
    "rebuildable_dev": "Rebuildable Dev",
    "reviewable_state": "Review First",
    "human_data": "Human Data",
}

ACTION_LABELS = {
    "delete": "Delete",
    "review": "Review",
    "archive": "Archive",
    "ignore": "Ignore",
    "keep": "Keep",
}

RISK_LABELS = {
    "safe": "[safe]",
    "low": "[low risk]",
    "medium": "[medium risk]",
    "high": "[high risk]",
}

MAX_RECOMMENDATIONS = 100
MIN_RECOMMENDATION_BYTES = 100 * 1024 * 1024
SORT_LADDER = "ladder"
SORT_SIZE = "size"
SORT_LABELS = {
    SORT_LADDER: "Ease",
    SORT_SIZE: "Size",
}


# ── Rules ────────────────────────────────────────────────────────────────────

CLEANUP_RULES = [
    # Human data and user-owned working sets
    CleanupRule(
        "*/Library/Messages/Attachments",
        "messages",
        "human_data",
        "high",
        "review",
        "Message attachments are real user content, not a cache",
        "Delete individual attachments in Messages or archive them elsewhere",
        "imessage_backup",
    ),
    CleanupRule(
        "*/Library/Application Support/*/User Data",
        "profile_data",
        "human_data",
        "high",
        "review",
        "Browser or app profile data may contain history, sessions, and downloads",
        "Use the app's own storage tools or sign in again after cleanup",
    ),
    CleanupRule(
        "*/Downloads",
        "downloads",
        "human_data",
        "medium",
        "review",
        "Downloads usually mix one-off installers with files you may still want",
        "Move important files elsewhere before deleting",
    ),
    CleanupRule(
        "*/NotesBackup",
        "backup",
        "human_data",
        "medium",
        "archive",
        "Named backup directory; likely valuable but not hot working data",
        "Archive to external storage or cloud backup before deleting",
    ),
    CleanupRule(
        "*.bak",
        "backup",
        "human_data",
        "medium",
        "archive",
        "Backup or snapshot directory; usually safe only after manual review",
        "Restore from the original source or archive it before deleting",
    ),

    # Review-first app/runtime state
    CleanupRule(
        "*/Library/Application Support/Claude/vm_bundles",
        "runtime_state",
        "reviewable_state",
        "medium",
        "review",
        "Claude VM bundles are large runtime assets, not simple throwaway caches",
        "Claude will re-provision them, but only after setup/downloading again",
    ),
    CleanupRule(
        "*/Library/Developer/Xcode/Archives",
        "build_archive",
        "reviewable_state",
        "medium",
        "review",
        "Xcode archives are often needed later for re-signing or submissions",
        "Re-archive from Xcode when needed, if the project still builds cleanly",
    ),
    CleanupRule(
        "*/Library/Containers/com.docker.docker",
        "dev_tools",
        "reviewable_state",
        "medium",
        "review",
        "Docker Desktop data includes images, containers, and local volumes",
        "Re-pull images and rebuild containers after cleanup",
    ),
    CleanupRule(
        "*/.cursor/extensions",
        "ide_state",
        "reviewable_state",
        "low",
        "review",
        "Cursor extensions are reinstallable, but removing them resets local setup",
        "Reinstall extensions from inside Cursor when needed",
    ),
    CleanupRule(
        "*/.windsurf/extensions",
        "ide_state",
        "reviewable_state",
        "low",
        "review",
        "Windsurf extensions are reinstallable, but removing them resets local setup",
        "Reinstall extensions from inside Windsurf when needed",
    ),

    # Purge-now caches and residue
    CleanupRule(
        "*/.Trash",
        "trash",
        "purge_now",
        "safe",
        "delete",
        "Already-deleted files awaiting permanent removal",
        "Items were already deleted by you",
    ),
    CleanupRule(
        "*/Library/Containers/*/Data/Library/Caches",
        "cache",
        "purge_now",
        "safe",
        "delete",
        "Containerized app caches, regenerated automatically by macOS apps",
        "Apps recreate these caches on next launch",
    ),
    CleanupRule(
        "*/Library/Application Support/*/Cache*",
        "cache",
        "purge_now",
        "safe",
        "delete",
        "Application support cache data that is typically rebuilt automatically",
        "The owning app recreates these files on next launch",
    ),
    CleanupRule(
        "*/Library/Messages/Caches",
        "cache",
        "purge_now",
        "safe",
        "delete",
        "Messages cache data, separate from your actual attachments and chat history",
        "Messages recreates caches as needed",
    ),
    CleanupRule(
        "*/Code Cache",
        "cache",
        "purge_now",
        "safe",
        "delete",
        "Compiled app code cache used only to speed startup",
        "The app rebuilds this cache automatically",
    ),
    CleanupRule(
        "*/GPUCache",
        "cache",
        "purge_now",
        "safe",
        "delete",
        "GPU shader cache; safe to rebuild",
        "The app regenerates it during rendering",
    ),
    CleanupRule(
        "*/Dawn*Cache",
        "cache",
        "purge_now",
        "safe",
        "delete",
        "WebGPU or graphics cache; safe to rebuild",
        "The app regenerates it during rendering",
    ),
    CleanupRule(
        "*/ShipIt",
        "cache",
        "purge_now",
        "safe",
        "delete",
        "Auto-updater residue that apps recreate when they self-update",
        "The app recreates it during the next update",
    ),
    CleanupRule(
        "*/Homebrew/Caches",
        "package_manager",
        "purge_now",
        "safe",
        "delete",
        "Homebrew download cache",
        "Packages re-download on install or upgrade",
    ),
    CleanupRule(
        "*/.npm",
        "package_manager",
        "purge_now",
        "safe",
        "delete",
        "npm global cache",
        "Rebuilt automatically by npm on next install",
    ),
    CleanupRule(
        "*/.yarn",
        "package_manager",
        "purge_now",
        "safe",
        "delete",
        "Yarn package cache",
        "Rebuilt automatically by Yarn on next install",
    ),
    CleanupRule(
        "*/.bun",
        "package_manager",
        "purge_now",
        "safe",
        "delete",
        "Bun runtime cache and installed packages",
        "Run `bun install` to restore packages",
    ),
    CleanupRule(
        "*/.cache",
        "cache",
        "purge_now",
        "safe",
        "delete",
        "General application cache directory",
        "Tools recreate their caches on next use",
    ),
    CleanupRule(
        "*/.cargo/registry",
        "package_manager",
        "purge_now",
        "safe",
        "delete",
        "Cargo registry cache",
        "Rebuilt automatically by `cargo build`",
    ),
    CleanupRule(
        "*/.gradle",
        "package_manager",
        "purge_now",
        "safe",
        "delete",
        "Gradle build cache and downloaded dependencies",
        "Rebuilt automatically on next Gradle build",
    ),
    CleanupRule(
        "*/.cocoapods",
        "package_manager",
        "purge_now",
        "safe",
        "delete",
        "CocoaPods spec repo cache",
        "Rebuilt on next `pod install`",
    ),
    CleanupRule(
        "*/.pub-cache",
        "package_manager",
        "purge_now",
        "safe",
        "delete",
        "Dart or Flutter package cache",
        "Run `flutter pub get` to restore packages",
    ),
    CleanupRule(
        "*/Library/Caches",
        "cache",
        "purge_now",
        "safe",
        "delete",
        "macOS application caches, regenerated automatically by apps",
        "Apps recreate their caches on next launch",
    ),
    CleanupRule(
        "*/Library/Logs",
        "logs",
        "purge_now",
        "safe",
        "delete",
        "Application log files, not needed for normal operation",
        "Apps create new logs as needed",
    ),

    # Rebuildable development artifacts
    CleanupRule(
        "*/Library/Developer/Xcode/DerivedData",
        "build_artifact",
        "rebuildable_dev",
        "safe",
        "delete",
        "Xcode build cache, fully regenerated on next build",
        "Xcode rebuilds automatically when you open a project",
    ),
    CleanupRule(
        "*/Library/Developer/Xcode/iOS DeviceSupport",
        "dev_tools",
        "rebuildable_dev",
        "low",
        "delete",
        "Debug symbols for connected iOS devices, re-downloaded on connect",
        "Reconnect your iOS device to re-download support files",
    ),
    CleanupRule(
        "*/Library/Developer/CoreSimulator",
        "dev_tools",
        "rebuildable_dev",
        "low",
        "review",
        "iOS Simulator runtimes and device data",
        "Re-download runtimes from Xcode settings when needed",
        "sim_cleanup",
    ),
    CleanupRule(
        "*/node_modules",
        "build_artifact",
        "rebuildable_dev",
        "low",
        "delete",
        "JavaScript dependencies restored from lockfiles or package manifests",
        "Run `npm install`, `yarn install`, or `bun install` in the project",
    ),
    CleanupRule(
        "*/.venv",
        "build_artifact",
        "rebuildable_dev",
        "low",
        "delete",
        "Python virtual environment, recreatable from requirements",
        "Run `python -m venv .venv && pip install -r requirements.txt`",
    ),
    CleanupRule(
        "*/venv",
        "build_artifact",
        "rebuildable_dev",
        "low",
        "delete",
        "Python virtual environment, recreatable from requirements",
        "Run `python -m venv venv && pip install -r requirements.txt`",
    ),
    CleanupRule(
        "*/__pycache__",
        "build_artifact",
        "rebuildable_dev",
        "safe",
        "delete",
        "Python bytecode cache, regenerated on import",
        "Python recreates these automatically",
    ),
    CleanupRule(
        "*/Pods",
        "build_artifact",
        "rebuildable_dev",
        "low",
        "delete",
        "CocoaPods dependencies restored from Podfile.lock",
        "Run `pod install` in the project",
    ),
    CleanupRule(
        "*/target",
        "build_artifact",
        "rebuildable_dev",
        "safe",
        "delete",
        "Rust or Cargo build artifacts",
        "Run `cargo build` to rebuild",
    ),
    CleanupRule(
        "*/.build",
        "build_artifact",
        "rebuildable_dev",
        "safe",
        "delete",
        "Swift Package Manager build artifacts",
        "Run `swift build` to rebuild",
    ),
]


# ── Matching Engine ──────────────────────────────────────────────────────────

_SEEN_PATHS_CACHE = {}  # scan_dir -> (root_mtime, dict)
_SEEN_PATHS_SIDECAR = ".seen_paths_cache.json"


def invalidate_seen_paths(scan_dir=None):
    """Drop the cached seen-paths map for ``scan_dir`` (or all if None).

    Also removes the on-disk sidecar so the next launch re-reads the
    snapshot fresh.
    """
    if scan_dir is None:
        targets = list(_SEEN_PATHS_CACHE.keys())
        _SEEN_PATHS_CACHE.clear()
    else:
        _SEEN_PATHS_CACHE.pop(scan_dir, None)
        targets = [scan_dir]
    for sd in targets:
        sidecar = os.path.join(sd, _SEEN_PATHS_SIDECAR)
        try:
            os.remove(sidecar)
        except OSError:
            pass


def _seen_paths_sidecar(scan_dir):
    return os.path.join(scan_dir, _SEEN_PATHS_SIDECAR)


def _try_read_sidecar(scan_dir):
    """Return seen_paths dict if a fresh sidecar exists, else None."""
    path = _seen_paths_sidecar(scan_dir)
    try:
        with open(path) as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return None
    # Sidecar entries are [size_bytes, size_str]; convert back to tuples.
    return {p: (int(v[0]), v[1]) for p, v in entries.items() if isinstance(v, list) and len(v) == 2}


def _write_sidecar(scan_dir, seen_paths):
    path = _seen_paths_sidecar(scan_dir)
    payload = {
        "version": 1,
        "entries": {p: [size_bytes, size_str] for p, (size_bytes, size_str) in seen_paths.items()},
    }
    try:
        with open(path, "w") as f:
            json.dump(payload, f)
    except OSError:
        pass  # cache is best-effort


def _load_seen_paths(scan_dir):
    """Collect unique paths with their parsed size from a scan directory.

    Memoized in-memory per scan_dir AND on-disk via a JSON sidecar
    (`.seen_paths_cache.json` inside the scan dir). The sidecar is
    deleted by `invalidate_seen_paths` whenever the snapshot mutates.
    Walking the mirrored tree fresh is multi-second on real machines
    (47k+ disk_usage.txt files); reading the sidecar is sub-100ms.
    """
    cached = _SEEN_PATHS_CACHE.get(scan_dir)
    if cached:
        return cached[1]

    sidecar = _try_read_sidecar(scan_dir)
    if sidecar is not None:
        _SEEN_PATHS_CACHE[scan_dir] = (None, sidecar)
        return sidecar

    seen_paths = {}
    for dirpath, _dirnames, filenames in os.walk(scan_dir):
        if "disk_usage.txt" not in filenames:
            continue
        du_file = os.path.join(dirpath, "disk_usage.txt")
        with open(du_file) as f:
            for line in f:
                line = line.strip()
                if not line or "\t" not in line:
                    continue
                size_str, path = line.split("\t", 1)
                path = os.path.normpath(path)
                try:
                    size_bytes = parse_size(size_str)
                except (ValueError, IndexError):
                    continue
                if path not in seen_paths or size_bytes > seen_paths[path][0]:
                    seen_paths[path] = (size_bytes, size_str)
    _SEEN_PATHS_CACHE[scan_dir] = (None, seen_paths)
    _write_sidecar(scan_dir, seen_paths)
    return seen_paths


def _sort_key(rec):
    """Sort by risk first, then size descending, then tier/actionability.

    This keeps higher-risk items later, but still allows a very large safe or
    low-risk opportunity to outrank tiny cache crumbs.
    """
    return (
        RISK_ORDER.get(rec.risk, 99),
        -rec.size_bytes,
        TIER_ORDER.get(rec.tier, 99),
        rec.path,
    )


def generate_recommendations(scan_dir, root_path=None, only_reviewed=False):
    """Walk scan output and match paths against opportunity ladder rules.

    Args:
        scan_dir: Path to a scan's output directory.
        root_path: Unused today, kept for compatibility with existing callers.

    Returns:
        List of Recommendation namedtuples sorted from lowest-hanging fruit
        upward.
    """
    del root_path  # kept for backwards compatibility with existing callers

    seen_paths = _load_seen_paths(scan_dir)
    reviewed = _load_reviewed_paths(scan_dir)
    active_projects = _load_active_projects()

    candidates = []
    for path, (size_bytes, _size_str) in seen_paths.items():
        if size_bytes < MIN_RECOMMENDATION_BYTES:
            continue
        if _is_under_active_project(path, active_projects):
            continue
        if only_reviewed:
            if path not in reviewed:
                continue
        elif path in reviewed:
            continue
        for rule in CLEANUP_RULES:
            if fnmatch.fnmatch(path, rule.pattern):
                risk = rule.risk
                tier = rule.tier
                rationale = rule.rationale
                regeneration = rule.regeneration
                basename = os.path.basename(os.path.normpath(path))
                if basename == "node_modules":
                    lockfile = _node_modules_lockfile(path)
                    if lockfile:
                        risk = "safe"
                        rationale = f"JavaScript dependencies — {os.path.basename(lockfile)} present, restorable exactly"
                    else:
                        risk = "medium"
                        tier = "reviewable_state"
                        rationale = "JavaScript dependencies — no lockfile in parent, review before deleting"
                elif basename in {"venv", ".venv", "env", ".env"} or os.path.isfile(os.path.join(path, "pyvenv.cfg")):
                    dep_file, is_lock = _venv_dependency_file(path)
                    if not dep_file:
                        risk = "medium"
                        tier = "reviewable_state"
                        rationale = "Python venv — no requirements/pyproject in parent, review before deleting"
                    elif is_lock:
                        risk = "safe"
                        rationale = f"Python venv — {os.path.basename(dep_file)} present, restorable exactly"
                tool_name = rule.tool
                if tool_name:
                    recipe = cleanup_tools.get(tool_name)
                    if not (recipe and recipe.applies_to(path)):
                        tool_name = None  # rule says tool, but this path doesn't qualify
                candidates.append(
                    Recommendation(
                        path=path,
                        size_bytes=size_bytes,
                        size_human=_format_bytes(size_bytes),
                        category=rule.category,
                        tier=tier,
                        risk=risk,
                        action=rule.action,
                        rationale=rationale,
                        regeneration=regeneration,
                        tool=tool_name,
                    )
                )
                break

    # Prefer parent directories for broad cache buckets so users can clear one
    # directory instead of many children, unless only the child matched.
    candidates.sort(key=lambda r: len(r.path))
    accepted = []
    for candidate in candidates:
        if not any(candidate.path.startswith(existing.path + "/") for existing in accepted):
            accepted.append(candidate)

    accepted.sort(key=_sort_key)
    return accepted[:MAX_RECOMMENDATIONS]


def _shorten_path(path):
    """Replace home directory prefix with ~ for display."""
    home = os.path.expanduser("~")
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


def _build_rows(recommendations):
    """Build a flat render list for the current sort order."""
    return [{"kind": "item", "rec": rec} for rec in recommendations]


def _build_active_project_recommendations(active_projects, scan_dir):
    """Synthesize Recommendation rows for the active-projects view."""
    seen_paths = _load_seen_paths(scan_dir) if scan_dir else {}
    recs = []
    for root in sorted(active_projects):
        size_bytes, _ = seen_paths.get(root, (0, ""))
        recs.append(
            Recommendation(
                path=root,
                size_bytes=size_bytes,
                size_human=_format_bytes(size_bytes) if size_bytes else "—",
                category="active_project",
                tier="reviewable_state",
                risk="safe",
                action="keep",
                rationale="Active project — excluded from recommendations",
                regeneration="",
            )
        )
    recs.sort(key=lambda r: (-r.size_bytes, r.path))
    return recs


def _sort_recommendations(recommendations, sort_mode):
    """Return recommendations ordered for the requested sort mode."""
    if sort_mode == SORT_SIZE:
        return sorted(
            recommendations,
            key=lambda rec: (-rec.size_bytes, RISK_ORDER.get(rec.risk, 99), rec.path),
        )
    return sorted(recommendations, key=_sort_key)


# ── TUI Display ──────────────────────────────────────────────────────────────

def _prompt_confirmation(stdscr, prompt):
    """Prompt for a y/n confirmation at the bottom of the screen."""
    height, width = stdscr.getmaxyx()
    try:
        stdscr.addstr(height - 1, 0, " " * max(0, width - 1))
        stdscr.addstr(height - 1, 0, prompt[: width - 1], curses.A_BOLD)
    except curses.error:
        pass
    stdscr.refresh()
    stdscr.nodelay(False)
    return stdscr.getch()


def _flash_message(stdscr, message, delay_ms=900):
    """Show a brief status message at the bottom of the screen."""
    height, width = stdscr.getmaxyx()
    try:
        stdscr.addstr(height - 1, 0, " " * max(0, width - 1))
        stdscr.addstr(height - 1, 0, message[: width - 1], curses.A_BOLD)
    except curses.error:
        pass
    stdscr.refresh()
    curses.napms(delay_ms)


def show_recommendations(stdscr, recommendations, scan_dir=None, root_path=None):
    """Fullscreen curses view showing cleanup recommendations."""
    curses.curs_set(0)
    curses.use_default_colors()

    curses.init_pair(20, curses.COLOR_GREEN, -1)   # safe
    curses.init_pair(21, curses.COLOR_YELLOW, -1)  # low
    curses.init_pair(22, curses.COLOR_RED, -1)     # medium/high
    curses.init_pair(23, curses.COLOR_CYAN, -1)    # header
    curses.init_pair(24, curses.COLOR_WHITE, curses.COLOR_BLUE)  # selected
    risk_color = {
        "safe": 20,
        "low": 21,
        "medium": 22,
        "high": 22,
    }

    has_any_reviewed = bool(_load_reviewed_paths(scan_dir)) if scan_dir else False
    has_any_active = bool(_load_active_projects())
    if not recommendations and not has_any_reviewed and not has_any_active:
        stdscr.clear()
        stdscr.addstr(2, 2, "No cleanup recommendations found.", curses.A_BOLD)
        stdscr.addstr(4, 2, "Run a scan first, or scan with a lower min-size threshold.")
        stdscr.addstr(6, 2, "Press any key to go back.")
        stdscr.refresh()
        stdscr.nodelay(False)
        stdscr.getch()
        return

    view_mode = "active"  # or "reviewed" or "active_projects"
    sort_mode = SORT_LADDER
    ordered_recommendations = _sort_recommendations(recommendations, sort_mode)
    rows = _build_rows(ordered_recommendations)
    selected = 0

    def rebuild_rows(current_sort, current_view):
        if current_view == "active_projects":
            synth = _build_active_project_recommendations(_load_active_projects(), scan_dir)
            return synth, synth, _build_rows(synth)
        only_reviewed = current_view == "reviewed"
        recs = generate_recommendations(scan_dir, root_path, only_reviewed=only_reviewed)
        ordered = _sort_recommendations(recs, current_sort)
        return recs, ordered, _build_rows(ordered)

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        total_bytes = sum(rec.size_bytes for rec in ordered_recommendations)
        total_human = _format_bytes(total_bytes)

        if view_mode == "reviewed":
            title = "Opportunity Ladder — Reviewed"
        elif view_mode == "active_projects":
            title = "Opportunity Ladder — Active Projects"
        else:
            title = "Opportunity Ladder"
        total_label = f"Sort: {SORT_LABELS[sort_mode]}  Shown: {total_human}"
        try:
            stdscr.addstr(0, 1, title, curses.color_pair(23) | curses.A_BOLD)
            stdscr.addstr(0, max(1, width - len(total_label) - 1), total_label, curses.A_BOLD)
            stdscr.addstr(1, 1, "=" * min(width - 2, 72), curses.color_pair(23))
        except curses.error:
            pass

        visible_area = max(1, height - 5)
        # Per-row heights: tool-bearing rows get an extra line for the
        # CTA. Rendered as primary + path + (CTA?) + blank gap.
        heights = []
        for r in rows:
            heights.append(4 if r["rec"].tool else 3)

        # Page size for PgUp/PgDn — approximate average so it still
        # advances by a screenful on tool-heavy ladders.
        avg_h = max(1, sum(heights) // max(1, len(heights)))
        max_visible_items = max(1, visible_area // avg_h)

        # Choose scroll_offset so that the selected row fits in the
        # visible area. Bump forward until cumulative height from
        # scroll_offset through selected (inclusive) fits.
        scroll_offset = 0
        while scroll_offset < selected and sum(heights[scroll_offset:selected + 1]) > visible_area:
            scroll_offset += 1

        y = 2

        for idx in range(scroll_offset, len(rows)):
            row = rows[idx]
            row_height = heights[idx]
            if y + row_height - 1 >= height - 2:
                break

            rec = row["rec"]
            is_selected = idx == selected
            attr = curses.A_REVERSE if is_selected else 0
            color = curses.color_pair(risk_color.get(rec.risk, 21))

            display_path = _shorten_path(rec.path)
            tool_recipe = cleanup_tools.get(rec.tool) if rec.tool else None
            rationale = rec.rationale
            if tool_recipe:
                # First render kicks off a background probe; subsequent
                # renders pick up the live summary once it's ready.
                live = cleanup_tools.cached_summary(tool_recipe, rec.path)
                if live:
                    rationale = live
            primary = "{action}: {rationale}".format(
                action=ACTION_LABELS.get(rec.action, rec.action),
                rationale=rationale,
            )
            tool_cta = (
                f"▸ Press T to open {tool_recipe.label}" if tool_recipe else None
            )
            num_col = "{num:>2}.".format(num=idx + 1)
            size_col = "{size:>6}".format(size=rec.size_human)
            risk_col = "{risk:<13}".format(risk=RISK_LABELS.get(rec.risk, rec.risk))
            tier_col = "{tier:<18}".format(tier="[{}]".format(TIER_LABELS.get(rec.tier, rec.tier)))

            num_x = 1
            size_x = num_x + 4
            risk_x = size_x + 8
            tier_x = risk_x + 14
            desc_x = tier_x + 19

            max_primary_len = max(10, width - desc_x - 1)
            if len(primary) > max_primary_len:
                primary = primary[: max_primary_len - 3] + "..."

            max_path_len = max(10, width - desc_x - 1)
            if len(display_path) > max_path_len:
                display_path = "..." + display_path[-(max_path_len - 3):]

            try:
                if num_x + len(num_col) < width:
                    stdscr.addstr(y, num_x, num_col, curses.A_BOLD | attr)
                if size_x + len(size_col) < width:
                    stdscr.addstr(y, size_x, size_col, curses.A_BOLD | attr)
                if risk_x + len(risk_col) < width:
                    stdscr.addstr(y, risk_x, risk_col, color | attr)
                if tier_x + len(tier_col) < width:
                    stdscr.addstr(
                        y,
                        tier_x,
                        tier_col,
                        curses.color_pair(23) | attr,
                    )
                if desc_x < width:
                    stdscr.addstr(y, desc_x, primary[: width - desc_x - 1], curses.A_BOLD | attr)
                    stdscr.addstr(y + 1, desc_x, display_path[: width - desc_x - 1], curses.A_DIM | attr)
                    if tool_cta and y + 2 < height - 2:
                        cta_attr = curses.color_pair(23) | curses.A_BOLD | attr
                        stdscr.addstr(y + 2, desc_x, tool_cta[: width - desc_x - 1], cta_attr)
            except curses.error:
                pass

            y += row_height

        try:
            footer_y = height - 2
            if view_mode == "reviewed":
                footer = "  ↑/↓: Nav  t: Sort  m: Unreview  p: Active-proj  V: Active  P: Projects  q: Back"
            elif view_mode == "active_projects":
                footer = "  ↑/↓: Nav  p: Unmark project  o: Finder  P: Back to Active  q: Back"
            else:
                selected_tool = None
                if rows and 0 <= selected < len(rows):
                    selected_tool = rows[selected]["rec"].tool
                tool_hint = ""
                if selected_tool:
                    recipe_for_hint = cleanup_tools.get(selected_tool)
                    if recipe_for_hint:
                        tool_hint = f"  T: {recipe_for_hint.label}"
                footer = (
                    "  ↑/↓: Nav  t: Sort  r: Rescan  a: AI  m: Review  p: Project"
                    + tool_hint
                    + "  V: Reviewed  P: Projects  x: Trash  q: Back"
                )
            stdscr.addstr(footer_y, 0, "─" * min(width - 1, 72))
            stdscr.addstr(
                footer_y + 1 if footer_y + 1 < height else footer_y,
                1,
                footer[: width - 2],
                curses.A_BOLD,
            )
        except curses.error:
            pass

        stdscr.refresh()
        stdscr.nodelay(False)
        key = stdscr.getch()

        if key == ord("q") or key == 27:
            break
        if key == ord("V"):
            view_mode = "active" if view_mode == "reviewed" else "reviewed"
            recommendations, ordered_recommendations, rows = rebuild_rows(sort_mode, view_mode)
            selected = 0
            continue
        if key == ord("P"):
            view_mode = "active" if view_mode == "active_projects" else "active_projects"
            recommendations, ordered_recommendations, rows = rebuild_rows(sort_mode, view_mode)
            selected = 0
            continue
        if not rows:
            try:
                stdscr.addstr(
                    height // 2,
                    2,
                    "Nothing to show here. Press V to toggle view, q to back out.",
                    curses.A_DIM,
                )
            except curses.error:
                pass
            continue
        if key == curses.KEY_UP:
            if selected > 0:
                selected -= 1
        elif key == curses.KEY_DOWN:
            if selected < len(rows) - 1:
                selected += 1
        elif key == curses.KEY_PPAGE:
            selected = max(0, selected - max_visible_items)
        elif key == curses.KEY_NPAGE:
            selected = min(len(rows) - 1, selected + max_visible_items)
        elif key == ord("o"):
            rec = rows[selected]["rec"]
            if os.path.exists(rec.path):
                curses.endwin()
                subprocess.run(["open", rec.path], check=False)
                stdscr.refresh()
        elif key == ord("a"):
            rec = rows[selected]["rec"]
            if not os.path.isdir(rec.path) or not _looks_like_venv(rec.path):
                _flash_message(stdscr, "AI-analyze only supports Python venvs right now.")
                continue
            prefs = _load_preferences()
            agent = prefs.get("ai_agent")
            ask_remember = False
            if agent not in AI_AGENTS:
                choice = _prompt_confirmation(
                    stdscr, "AI agent? (c)laude / (x) codex / (esc) cancel"
                )
                if choice == ord("c"):
                    agent = "claude"
                elif choice == ord("x"):
                    agent = "codex"
                else:
                    continue
                ask_remember = True
            if ask_remember:
                remember = _prompt_confirmation(
                    stdscr, f"Remember '{agent}' for next time? (y/n)"
                )
                if remember == ord("y"):
                    prefs["ai_agent"] = agent
                    try:
                        _save_preferences(prefs)
                    except OSError as exc:
                        _flash_message(stdscr, f"Could not save preference: {exc}")
            try:
                _launch_ai_agent_for_venv(agent, rec.path)
                _flash_message(stdscr, f"Launched {agent} in Terminal.")
            except Exception as exc:
                _flash_message(stdscr, f"Launch failed: {exc}")
            continue
        elif key == ord("T"):
            rec = rows[selected]["rec"]
            if not rec.tool:
                _flash_message(stdscr, "No specialized tool for this row.")
                continue
            recipe = cleanup_tools.get(rec.tool)
            if not recipe:
                _flash_message(stdscr, f"Unknown tool: {rec.tool}")
                continue
            helpers = {
                "load_prefs": _load_preferences,
                "save_prefs": _save_preferences,
                "flash": lambda m: _flash_message(stdscr, m),
            }
            try:
                msg = recipe.launch(stdscr, rec.path, helpers)
            except Exception as exc:
                msg = f"Tool launch failed: {exc}"
            if msg:
                _flash_message(stdscr, msg)
            # After tool exits, drop the cached summary for this row and
            # rebuild so any size / state change is reflected.
            cleanup_tools.invalidate_summary(rec.path)
            if scan_dir:
                recommendations, ordered_recommendations, rows = rebuild_rows(sort_mode, view_mode)
                if rows:
                    selected = min(selected, len(rows) - 1)
            continue
        elif key == ord("t"):
            selected_path = rows[selected]["rec"].path
            sort_mode = SORT_SIZE if sort_mode == SORT_LADDER else SORT_LADDER
            ordered_recommendations = _sort_recommendations(recommendations, sort_mode)
            rows = _build_rows(ordered_recommendations)
            for idx, row in enumerate(rows):
                if row["rec"].path == selected_path:
                    selected = idx
                    break
        elif key == ord("r"):
            rec = rows[selected]["rec"]
            if not scan_dir or not root_path:
                _flash_message(stdscr, "Cannot rescan: scan context unavailable.")
                continue
            cleanup_tools.invalidate_summary(rec.path)
            try:
                if not os.path.exists(rec.path):
                    remove_path_from_scan(scan_dir, root_path, rec.path)
                    msg = "Path gone — removed from scan."
                else:
                    new_size = measure_path_size_bytes(rec.path)
                    update_path_size_in_scan(scan_dir, root_path, rec.path, new_size)
                    msg = f"Rescanned: {_format_bytes(new_size)}"
                invalidate_seen_paths(scan_dir)
                recommendations = generate_recommendations(scan_dir, root_path, only_reviewed=(view_mode == "reviewed"))
                ordered_recommendations = _sort_recommendations(recommendations, sort_mode)
                rows = _build_rows(ordered_recommendations)
                if rows:
                    selected = min(selected, len(rows) - 1)
                _flash_message(stdscr, msg)
            except Exception as exc:
                _flash_message(stdscr, f"Rescan failed: {exc}")
            continue
        elif key == ord("p"):
            rec = rows[selected]["rec"]
            try:
                projects = _load_active_projects()
                if view_mode == "active_projects":
                    projects.discard(os.path.normpath(rec.path))
                    _save_active_projects(projects)
                    msg = "Unmarked active project."
                else:
                    root = _active_project_root_for_path(rec.path)
                    projects.add(root)
                    _save_active_projects(projects)
                    msg = f"Active project: {_shorten_path(root)}"
                recommendations, ordered_recommendations, rows = rebuild_rows(sort_mode, view_mode)
                if rows:
                    selected = min(selected, len(rows) - 1)
                _flash_message(stdscr, msg)
            except Exception as exc:
                _flash_message(stdscr, f"Active-project update failed: {exc}")
            continue
        elif key == ord("m"):
            rec = rows[selected]["rec"]
            if not scan_dir:
                _flash_message(stdscr, "Cannot update reviewed: no scan directory.")
                continue
            try:
                reviewed = _load_reviewed_paths(scan_dir)
                if view_mode == "reviewed":
                    reviewed.discard(rec.path)
                    msg = "Unmarked."
                else:
                    reviewed.add(rec.path)
                    msg = "Marked reviewed."
                _save_reviewed_paths(scan_dir, reviewed)
                recommendations = generate_recommendations(scan_dir, root_path, only_reviewed=(view_mode == "reviewed"))
                ordered_recommendations = _sort_recommendations(recommendations, sort_mode)
                rows = _build_rows(ordered_recommendations)
                if rows:
                    selected = min(selected, len(rows) - 1)
                _flash_message(stdscr, msg)
            except Exception as exc:
                _flash_message(stdscr, f"Update failed: {exc}")
            continue
        elif key == ord("x"):
            rec = rows[selected]["rec"]
            if not os.path.exists(rec.path):
                if scan_dir and root_path:
                    try:
                        remove_path_from_scan(scan_dir, root_path, rec.path)
                        invalidate_seen_paths(scan_dir)
                        recommendations = generate_recommendations(scan_dir, root_path, only_reviewed=(view_mode == "reviewed"))
                        ordered_recommendations = _sort_recommendations(recommendations, sort_mode)
                        rows = _build_rows(ordered_recommendations)
                        if rows:
                            selected = min(selected, len(rows) - 1)
                        _flash_message(stdscr, "Path already gone — removed from list.")
                    except Exception as exc:
                        _flash_message(stdscr, f"Path gone; cleanup failed: {exc}")
                else:
                    _flash_message(stdscr, "Path no longer exists.")
                continue
            prompt = f"Move to Trash? {rec.size_human} {_shorten_path(rec.path)} (y/n)"
            if rec.action != "delete":
                prompt = f"Tagged {ACTION_LABELS.get(rec.action, rec.action)}. Move to Trash anyway? (y/n)"
            confirm = _prompt_confirmation(stdscr, prompt)
            if confirm != ord("y"):
                continue
            try:
                move_path_to_trash(rec.path)
                if scan_dir and root_path:
                    remove_path_from_scan(scan_dir, root_path, rec.path)
                    invalidate_seen_paths(scan_dir)
                    recommendations = generate_recommendations(scan_dir, root_path, only_reviewed=(view_mode == "reviewed"))
                    ordered_recommendations = _sort_recommendations(recommendations, sort_mode)
                    rows = _build_rows(ordered_recommendations)
                    if rows:
                        selected = min(selected, len(rows) - 1)
                _flash_message(stdscr, "Moved to Trash.")
            except Exception as exc:
                _flash_message(stdscr, f"Trash failed: {exc}")
        elif key == curses.KEY_RESIZE:
            pass
