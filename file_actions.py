"""Shared file actions for the disk analyzer TUI."""

import os
import shutil


def _scan_file_path(scan_dir, root_path, path):
    """Return the mirrored disk_usage.txt path for a filesystem path."""
    norm_root = os.path.normpath(root_path)
    norm_path = os.path.normpath(path)
    if norm_path == norm_root:
        return os.path.join(scan_dir, "disk_usage.txt")

    rel_path = os.path.relpath(norm_path, norm_root)
    return os.path.join(scan_dir, rel_path, "disk_usage.txt")


def _scan_subtree_dir(scan_dir, root_path, path):
    """Return the mirrored output directory for a filesystem path."""
    norm_root = os.path.normpath(root_path)
    norm_path = os.path.normpath(path)
    if norm_path == norm_root:
        return scan_dir

    rel_path = os.path.relpath(norm_path, norm_root)
    return os.path.join(scan_dir, rel_path)


def _parse_size_to_bytes(size_str):
    """Convert a size string like 2.5G into bytes."""
    size_str = size_str.strip()
    multiplier = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4, "B": 1}
    if not size_str:
        return 0
    try:
        unit = size_str[-1].upper()
        if unit in multiplier:
            return float(size_str[:-1]) * multiplier[unit]
        return float(size_str)
    except ValueError:
        return 0


def _format_bytes_human(size_bytes):
    """Convert bytes to the du-like strings used in scan snapshots."""
    if size_bytes == 0:
        return "0B"
    units = [(1024**4, "T"), (1024**3, "G"), (1024**2, "M"), (1024, "K")]
    for threshold, unit in units:
        if size_bytes >= threshold:
            value = size_bytes / threshold
            if value >= 10:
                return f"{value:.0f}{unit}"
            return f"{value:.1f}{unit}"
    return f"{size_bytes:.0f}B"


def _next_trash_destination(path):
    """Return a unique destination path inside ~/.Trash."""
    trash_dir = os.path.expanduser("~/.Trash")
    os.makedirs(trash_dir, exist_ok=True)

    base_name = os.path.basename(os.path.normpath(path)) or "trashed-item"
    candidate = os.path.join(trash_dir, base_name)
    if not os.path.exists(candidate):
        return candidate

    stem, ext = os.path.splitext(base_name)
    counter = 2
    while True:
        candidate = os.path.join(trash_dir, f"{stem} {counter}{ext}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def move_path_to_trash(path):
    """Move a file or directory to ~/.Trash and return the destination."""
    destination = _next_trash_destination(path)
    shutil.move(path, destination)
    return destination


def remove_path_from_scan(scan_dir, root_path, target_path):
    """Remove a deleted path from the mirrored scan snapshot.

    This updates the deleted entry's parent `disk_usage.txt`, then propagates the
    new aggregate sizes up to the scan root. The deleted path's mirrored subtree
    is removed from the output snapshot.
    """
    norm_root = os.path.normpath(root_path)
    norm_target = os.path.normpath(target_path)
    if norm_target == norm_root:
        raise ValueError("Refusing to remove the scan root from the snapshot")

    child_path = norm_target
    remove_child = True
    updated_size = None

    while os.path.normpath(child_path) != norm_root:
        parent_path = os.path.dirname(child_path)
        parent_file = _scan_file_path(scan_dir, norm_root, parent_path)
        if not os.path.exists(parent_file):
            break

        with open(parent_file) as f:
            original_lines = [line.rstrip("\n") for line in f]

        rewritten = []
        child_found = False
        parent_total = 0
        parent_norm = os.path.normpath(parent_path)

        for line in original_lines:
            if "\t" not in line:
                continue
            size_str, path = line.split("\t", 1)
            norm_line_path = os.path.normpath(path)

            if norm_line_path == os.path.normpath(child_path):
                child_found = True
                if remove_child:
                    continue
                size_str = updated_size

            rewritten.append((size_str, path))
            if norm_line_path != parent_norm:
                parent_total += _parse_size_to_bytes(size_str)

        if not child_found:
            break

        parent_size_str = _format_bytes_human(parent_total)
        final_lines = []
        for size_str, path in rewritten:
            if os.path.normpath(path) == parent_norm:
                final_lines.append(f"{parent_size_str}\t{path}\n")
            else:
                final_lines.append(f"{size_str}\t{path}\n")

        with open(parent_file, "w") as f:
            f.writelines(final_lines)

        child_path = parent_path
        updated_size = parent_size_str
        remove_child = False

    subtree_dir = _scan_subtree_dir(scan_dir, norm_root, norm_target)
    if os.path.isdir(subtree_dir):
        shutil.rmtree(subtree_dir, ignore_errors=True)
