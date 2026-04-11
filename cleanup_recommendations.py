"""Cleanup recommendation engine for disk-analyzer.

Scans analysis output for known cleanup opportunities and ranks them as an
"opportunity ladder": safest, largest, and most reversible items first.
"""

import curses
import fnmatch
import os
import subprocess
from collections import namedtuple

from disk_analyzer import parse_size, _format_bytes

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
    ],
)
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
    ],
)

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
}

RISK_LABELS = {
    "safe": "[safe]",
    "low": "[low risk]",
    "medium": "[medium risk]",
    "high": "[high risk]",
}

MAX_RECOMMENDATIONS = 100
MIN_RECOMMENDATION_BYTES = 100 * 1024 * 1024


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
        "delete",
        "iOS Simulator runtimes and device data",
        "Re-download runtimes from Xcode settings when needed",
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

def _load_seen_paths(scan_dir):
    """Collect unique paths with their parsed size from a scan directory."""
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


def generate_recommendations(scan_dir, root_path=None):
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

    candidates = []
    for path, (size_bytes, _size_str) in seen_paths.items():
        if size_bytes < MIN_RECOMMENDATION_BYTES:
            continue
        for rule in CLEANUP_RULES:
            if fnmatch.fnmatch(path, rule.pattern):
                candidates.append(
                    Recommendation(
                        path=path,
                        size_bytes=size_bytes,
                        size_human=_format_bytes(size_bytes),
                        category=rule.category,
                        tier=rule.tier,
                        risk=rule.risk,
                        action=rule.action,
                        rationale=rule.rationale,
                        regeneration=rule.regeneration,
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
    """Build a flat render list with tier headers and items."""
    rows = []
    current_tier = None
    for rec in recommendations:
        if rec.tier != current_tier:
            current_tier = rec.tier
            tier_total = sum(
                item.size_bytes for item in recommendations if item.tier == current_tier
            )
            rows.append(
                {
                    "kind": "header",
                    "tier": current_tier,
                    "label": TIER_LABELS.get(current_tier, current_tier),
                    "total_human": _format_bytes(tier_total),
                }
            )
        rows.append({"kind": "item", "rec": rec})
    return rows


# ── TUI Display ──────────────────────────────────────────────────────────────

def show_recommendations(stdscr, recommendations):
    """Fullscreen curses view showing cleanup recommendations."""
    curses.curs_set(0)
    curses.use_default_colors()

    curses.init_pair(20, curses.COLOR_GREEN, -1)   # safe
    curses.init_pair(21, curses.COLOR_YELLOW, -1)  # low
    curses.init_pair(22, curses.COLOR_RED, -1)     # medium/high
    curses.init_pair(23, curses.COLOR_CYAN, -1)    # header
    curses.init_pair(24, curses.COLOR_WHITE, curses.COLOR_BLUE)  # selected
    curses.init_pair(25, curses.COLOR_MAGENTA, -1)  # tier header

    risk_color = {
        "safe": 20,
        "low": 21,
        "medium": 22,
        "high": 22,
    }

    if not recommendations:
        stdscr.clear()
        stdscr.addstr(2, 2, "No cleanup recommendations found.", curses.A_BOLD)
        stdscr.addstr(4, 2, "Run a scan first, or scan with a lower min-size threshold.")
        stdscr.addstr(6, 2, "Press any key to go back.")
        stdscr.refresh()
        stdscr.nodelay(False)
        stdscr.getch()
        return

    rows = _build_rows(recommendations)
    selected = 0
    while selected < len(rows) and rows[selected]["kind"] != "item":
        selected += 1
    if selected >= len(rows):
        return

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        total_bytes = sum(rec.size_bytes for rec in recommendations)
        total_human = _format_bytes(total_bytes)

        title = "Opportunity Ladder"
        total_label = f"Shown: {total_human}"
        try:
            stdscr.addstr(0, 1, title, curses.color_pair(23) | curses.A_BOLD)
            stdscr.addstr(0, max(1, width - len(total_label) - 1), total_label, curses.A_BOLD)
            stdscr.addstr(1, 1, "=" * min(width - 2, 72), curses.color_pair(23))
        except curses.error:
            pass

        visible_area = max(1, height - 5)
        scroll_offset = 0
        item_line = 0
        for idx, row in enumerate(rows):
            line_cost = 1 if row["kind"] == "header" else 3
            if row["kind"] == "item" and idx == selected:
                break
            item_line += line_cost
        while item_line - scroll_offset >= visible_area:
            scroll_offset += 1

        y = 2
        item_number = 0
        consumed = 0

        for idx, row in enumerate(rows):
            line_cost = 1 if row["kind"] == "header" else 3
            if consumed + line_cost <= scroll_offset:
                if row["kind"] == "item":
                    item_number += 1
                consumed += line_cost
                continue
            if y >= height - 2:
                break

            if row["kind"] == "header":
                header = f"{row['label']}  ({row['total_human']})"
                try:
                    stdscr.addstr(y, 1, header[: width - 2], curses.color_pair(25) | curses.A_BOLD)
                except curses.error:
                    pass
                y += 1
                consumed += 1
                continue

            rec = row["rec"]
            item_number += 1
            is_selected = idx == selected
            attr = curses.A_REVERSE if is_selected else 0
            color = curses.color_pair(risk_color.get(rec.risk, 21))

            display_path = _shorten_path(rec.path)
            size_and_badges = "  {size:>6}  [{tier}] {risk}".format(
                size=rec.size_human,
                tier=TIER_LABELS.get(rec.tier, rec.tier),
                risk=RISK_LABELS.get(rec.risk, rec.risk),
            )
            max_path_len = max(10, width - len(size_and_badges) - 6)
            if len(display_path) > max_path_len:
                display_path = "..." + display_path[-(max_path_len - 3):]

            line1 = "{num:>2}. {path}".format(num=item_number, path=display_path)
            line2 = "     {action}: {rationale}".format(
                action=ACTION_LABELS.get(rec.action, rec.action),
                rationale=rec.rationale,
            )

            try:
                stdscr.addstr(y, 1, line1[: width - 2], curses.A_BOLD | attr)
                badge_x = max(len(line1) + 2, width - len(size_and_badges) - 1)
                if badge_x + len(size_and_badges) < width:
                    stdscr.addstr(y, badge_x, "  {0:>6}  ".format(rec.size_human), attr)
                    tier_label = "[{0}]".format(TIER_LABELS.get(rec.tier, rec.tier))
                    stdscr.addstr(
                        y,
                        badge_x + len("  {0:>6}  ".format(rec.size_human)),
                        tier_label,
                        curses.color_pair(23) | attr,
                    )
                    risk_x = badge_x + len("  {0:>6}  ".format(rec.size_human)) + len(tier_label) + 1
                    if risk_x + len(RISK_LABELS.get(rec.risk, rec.risk)) < width:
                        stdscr.addstr(
                            y,
                            risk_x,
                            RISK_LABELS.get(rec.risk, rec.risk),
                            color | attr,
                        )

                stdscr.addstr(y + 1, 1, line2[: width - 2], curses.A_DIM | attr)
            except curses.error:
                pass

            y += 3
            consumed += 3

        try:
            footer_y = height - 2
            footer = "  ↑/↓: Navigate  o: Open in Finder  q: Back"
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
        if key == curses.KEY_UP:
            while selected > 0:
                selected -= 1
                if rows[selected]["kind"] == "item":
                    break
        elif key == curses.KEY_DOWN:
            while selected < len(rows) - 1:
                selected += 1
                if rows[selected]["kind"] == "item":
                    break
        elif key == ord("o"):
            rec = rows[selected]["rec"]
            if os.path.exists(rec.path):
                curses.endwin()
                subprocess.run(["open", rec.path], check=False)
                stdscr.refresh()
        elif key == curses.KEY_RESIZE:
            pass
