"""Compare saved scan snapshots to see which folders grew.

A scan writes <output_dir>/<YYYY-MM-DD_HH-MM-SS>/disk_usage.txt plus one
disk_usage.txt per recursed folder, mirroring the folder tree. Each line is
"<du -h size>\t<absolute path>"; the first line is the folder itself.

Used by the TUI browser's change column and by `disk-analyzer changes`.
"""

import datetime
import os

SNAPSHOT_FORMAT = "%Y-%m-%d_%H-%M-%S"
USAGE_FILE = "disk_usage.txt"

_MULTIPLIER = {'B': 1, 'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4}


def parse_size_to_bytes(size_str):
    """Convert a du -h size like '2.5G' to bytes (0 when unparseable)."""
    if not size_str or size_str == "?":
        return 0
    size_str = size_str.strip()
    try:
        unit = size_str[-1].upper()
        if unit in _MULTIPLIER:
            return float(size_str[:-1]) * _MULTIPLIER[unit]
        return float(size_str)
    except (ValueError, IndexError):
        return 0


def format_delta(delta, format_bytes):
    """'+2.3G' / '-1.1G', '·' for zero, '—' for no data."""
    if delta is None:
        return "—"
    if delta == 0:
        return "·"
    return ("+" if delta > 0 else "-") + format_bytes(abs(delta))


def list_snapshots(output_dir):
    """[(dir_name, datetime)] for every snapshot folder, newest first."""
    snapshots = []
    try:
        names = os.listdir(output_dir)
    except OSError:
        return []
    for name in names:
        if not os.path.isdir(os.path.join(output_dir, name)):
            continue
        try:
            snapshots.append((name, datetime.datetime.strptime(name, SNAPSHOT_FORMAT)))
        except ValueError:
            continue
    snapshots.sort(key=lambda s: s[1], reverse=True)
    return snapshots


def pick_baseline(snapshots, selected_time, days):
    """The snapshot strictly older than selected_time closest to selected_time - days.

    Returns (dir_name, datetime) or None."""
    target = selected_time - datetime.timedelta(days=days)
    best = None
    best_distance = None
    for name, ts in snapshots:
        if ts >= selected_time:
            continue
        distance = abs((ts - target).total_seconds())
        if best_distance is None or distance < best_distance:
            best, best_distance = (name, ts), distance
    return best


def _read_usage_file(path):
    """[(size_str, normpath)] from one disk_usage.txt ([] if missing)."""
    rows = []
    try:
        with open(path) as f:
            for line in f:
                parts = line.rstrip('\n').split('\t')
                if len(parts) == 2:
                    rows.append((parts[0], os.path.normpath(parts[1])))
    except OSError:
        pass
    return rows


def snapshot_root(snapshot_dir):
    """The scan root of a snapshot (first line of its top disk_usage.txt), or None."""
    rows = _read_usage_file(os.path.join(snapshot_dir, USAGE_FILE))
    return rows[0][1] if rows else None


def read_children(snapshot_dir, folder, root=None):
    """({child_path: bytes}, folder_was_scanned) for one folder in a snapshot.

    Reads only the disk_usage.txt that mirrors `folder`. folder_was_scanned is
    True when that file exists, so children missing from it are genuinely new
    (or newly above the scan's min size)."""
    root = root or snapshot_root(snapshot_dir)
    if not root:
        return {}, False
    rel = os.path.relpath(folder, root)
    if rel.startswith('..'):
        return {}, False
    usage = os.path.join(snapshot_dir, USAGE_FILE) if rel == '.' else \
        os.path.join(snapshot_dir, rel, USAGE_FILE)
    if not os.path.exists(usage):
        return {}, False
    return {p: parse_size_to_bytes(s) for s, p in _read_usage_file(usage)}, True


def compute_delta(path, size_bytes, ref_sizes, folder_was_scanned):
    """Bytes gained vs the baseline, or None when the baseline can't say.

    - in baseline                 -> current - baseline
    - missing, parent was scanned -> +current (appeared, or grew past min size)
    - parent not scanned then     -> None"""
    key = os.path.normpath(path)
    if key in ref_sizes:
        return size_bytes - ref_sizes[key]
    if folder_was_scanned:
        return size_bytes
    return None


def load_snapshot(snapshot_dir):
    """({path: bytes} for every listed folder, {folders that were recursed})."""
    sizes, scanned = {}, set()
    for dirpath, _dirs, files in os.walk(snapshot_dir):
        if USAGE_FILE not in files:
            continue
        rows = _read_usage_file(os.path.join(dirpath, USAGE_FILE))
        if not rows:
            continue
        scanned.add(rows[0][1])
        for size_str, path in rows:
            sizes[path] = parse_size_to_bytes(size_str)
    return sizes, scanned


def top_changes(output_dir, days=7, min_bytes=500 * 1024**2, top=15, shrink=False):
    """Biggest growers (or shrinkers) between the newest snapshot and ~days earlier.

    A folder is reported only where its change isn't mostly explained by one
    of its listed children, so the list points at the folder that actually grew.

    Returns dict(newest, baseline, interval_days, rows=[(delta, path, size, is_new)]),
    or None when there aren't two snapshots to compare."""
    snapshots = list_snapshots(output_dir)
    if len(snapshots) < 2:
        return None
    newest_name, newest_time = snapshots[0]
    base = pick_baseline(snapshots, newest_time, days)
    if not base:
        return None
    base_name, base_time = base

    cur_sizes, _ = load_snapshot(os.path.join(output_dir, newest_name))
    ref_sizes, ref_scanned = load_snapshot(os.path.join(output_dir, base_name))

    sign = -1 if shrink else 1
    deltas = {}
    for path, size in cur_sizes.items():
        delta = compute_delta(path, size, ref_sizes, os.path.dirname(path) in ref_scanned)
        if delta is not None and sign * delta >= min_bytes:
            deltas[path] = delta
    if shrink:
        for path, size in ref_sizes.items():
            if path not in cur_sizes and os.path.dirname(path) in ref_scanned and size >= min_bytes:
                parent = os.path.dirname(path)
                # only count as gone when its parent was listed in the new scan too
                if parent in cur_sizes:
                    deltas[path] = -size

    # Drop a folder when one child accounts for at least half of its change
    explained = set()
    for path, delta in deltas.items():
        parent = os.path.dirname(path)
        if parent in deltas and parent != path and sign * delta >= sign * deltas[parent] * 0.5:
            explained.add(parent)

    rows = [(d, p, cur_sizes.get(p, 0), p not in ref_sizes)
            for p, d in deltas.items() if p not in explained]
    rows.sort(key=lambda r: -sign * r[0])
    return dict(newest=(newest_name, newest_time), baseline=(base_name, base_time),
                interval_days=(newest_time - base_time).total_seconds() / 86400,
                rows=rows[:top])
