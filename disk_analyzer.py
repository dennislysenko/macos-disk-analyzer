#!/usr/bin/env python3

import os
import subprocess
import argparse
from pathlib import Path
import re
import datetime
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

def _normalize_path(path_str):
    """Resolve a path without failing if it doesn't exist."""
    try:
        return Path(path_str).resolve(strict=False)
    except Exception:
        return Path(path_str)

EXCLUDED_PATHS = [
    _normalize_path("/System/Volumes"),
    _normalize_path("/System"),  # read-only sealed volume; firmlinks cause double-counting with Data volume
    _normalize_path("/dev"),
    _normalize_path("/proc"),
    _normalize_path("/sys"),
    _normalize_path("/private/var/vm"),
    _normalize_path("/private/var/folders"),
    _normalize_path("/.Spotlight-V100"),
    _normalize_path("/.fseventsd"),
    _normalize_path("/Volumes"),  # avoid double-counting mounted volumes
]

# Logging setup
log = logging.getLogger("disk_analyzer")
_print_lock = threading.Lock()

def is_excluded_path(path_str):
    """Return True if the given path is in, or under, an excluded path."""
    normalized = _normalize_path(path_str)
    return any(normalized == excluded or excluded in normalized.parents for excluded in EXCLUDED_PATHS)

def filter_excluded_entries(du_output):
    """Remove du output lines that point to excluded paths."""
    filtered_lines = []
    for line in du_output.splitlines():
        parts = line.split('\t', 1)
        if len(parts) == 2 and is_excluded_path(parts[1].strip()):
            continue
        filtered_lines.append(line)
    return '\n'.join(filtered_lines)

def parse_size(size_str):
    """Convert size string with units to bytes."""
    units = {'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4}
    size_str = size_str.upper()
    
    if size_str[-1] in units:
        return float(size_str[:-1]) * units[size_str[-1]]
    return float(size_str)

def format_path_for_output(base_path, target_path):
    """Format path to create corresponding structure in output directory."""
    rel_path = os.path.relpath(target_path, base_path)
    return rel_path if rel_path != '.' else os.path.basename(base_path)

def run_du_command(directory, use_sudo=False, quiet=False, timeout_seconds=300):
    """Run the du command on the specified directory and sort results.

    timeout_seconds is a soft timeout: logs a warning but does NOT kill the process.
    """
    du_cmd = ["sudo", "du", "-h", "-d", "1", directory] if use_sudo else ["du", "-h", "-d", "1", directory]

    try:
        t0 = time.monotonic()

        if quiet:
            with open(os.devnull, 'w') as devnull:
                du_result = subprocess.run(
                    du_cmd,
                    stdout=subprocess.PIPE,
                    stderr=devnull,
                    text=True,
                    check=False,
                )
        else:
            du_result = subprocess.run(
                du_cmd,
                capture_output=True,
                text=True,
                check=False,
            )

        elapsed = time.monotonic() - t0
        log.info(f"du finished in {elapsed:.1f}s for {directory} ({len(du_result.stdout.splitlines())} lines)")

        if elapsed > timeout_seconds:
            log.warning(f"SOFT TIMEOUT: {directory} took {elapsed:.1f}s (threshold {timeout_seconds}s)")
            with _print_lock:
                print(f"  SLOW: {directory} took {elapsed:.1f}s (soft timeout was {timeout_seconds}s)")
        elif elapsed > 10:
            log.warning(f"SLOW: {directory} took {elapsed:.1f}s")

        if du_result.returncode != 0 and not quiet:
            with _print_lock:
                print(f"Warning: du command on {directory} exited with code {du_result.returncode}")
                if du_result.stderr:
                    stderr_lines = du_result.stderr.strip().splitlines()
                    print(f"  ({len(stderr_lines)} error lines, first: {stderr_lines[0][:120] if stderr_lines else ''})")

        # Sort the output
        sort_cmd = ["sort", "-hr"]
        sort_process = subprocess.run(
            sort_cmd,
            input=du_result.stdout,
            capture_output=True,
            text=True
        )

        return sort_process.stdout
    except subprocess.SubprocessError as e:
        if not quiet:
            with _print_lock:
                print(f"Error running command on {directory}: {e}")
        return ""

def create_output_dir(output_base, path_component):
    """Create output directory maintaining structure."""
    output_dir = os.path.join(output_base, path_component)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

def save_results(output_path, content):
    """Save the du command results to a file."""
    with open(output_path, "w") as f:
        f.write(content)

class AnalysisStats:
    """Track analysis statistics for the summary."""
    def __init__(self):
        self.lock = threading.Lock()
        self.dirs_analyzed = 0
        self.dirs_skipped = 0
        self.dirs_timed_out = 0
        self.slowest_dirs = []  # (elapsed, path) tuples
        self.start_time = time.monotonic()

    def record(self, directory, elapsed):
        with self.lock:
            self.dirs_analyzed += 1
            self.slowest_dirs.append((elapsed, directory))
            self.slowest_dirs.sort(reverse=True)
            self.slowest_dirs = self.slowest_dirs[:10]

    def record_skip(self):
        with self.lock:
            self.dirs_skipped += 1

    def record_timeout(self):
        with self.lock:
            self.dirs_timed_out += 1

    def summary(self):
        total = time.monotonic() - self.start_time
        lines = [
            f"\n{'='*60}",
            f"Analysis Summary",
            f"{'='*60}",
            f"Total wall time:     {total:.1f}s",
            f"Directories analyzed: {self.dirs_analyzed}",
            f"Directories skipped:  {self.dirs_skipped}",
            f"Directories timed out: {self.dirs_timed_out}",
        ]
        if self.slowest_dirs:
            lines.append(f"\nTop {len(self.slowest_dirs)} slowest directories:")
            for elapsed, path in self.slowest_dirs:
                lines.append(f"  {elapsed:6.1f}s  {path}")
        lines.append(f"{'='*60}")
        return "\n".join(lines)


# Global stats object and thread pool, set in main()
_stats = None
_executor = None


def analyze_single_directory(directory, output_base, base_directory, min_size_gb=2,
                             use_sudo=False, quiet=False, timeout_seconds=300):
    """
    Analyze one directory: run du, save output, return list of large subdirs.
    Does NOT recurse — caller handles the queue.
    """
    if is_excluded_path(directory):
        log.info(f"Skipping excluded: {directory}")
        if _stats:
            _stats.record_skip()
        if not quiet:
            with _print_lock:
                print(f"Skipping excluded directory: {directory}")
        return []

    with _print_lock:
        print(f"Analyzing: {directory}")

    t0 = time.monotonic()

    du_output = run_du_command(directory, use_sudo, quiet, timeout_seconds)
    if not du_output:
        if _stats:
            _stats.record_timeout()
        return []

    elapsed = time.monotonic() - t0
    if _stats:
        _stats.record(directory, elapsed)

    du_output = filter_excluded_entries(du_output)
    if not du_output.strip():
        return []

    # Create output structure
    path_component = format_path_for_output(base_directory, directory)

    if os.path.normpath(directory) == os.path.normpath(base_directory):
        output_dir = output_base
    else:
        output_dir = os.path.join(output_base, path_component)
        os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, "disk_usage.txt")
    save_results(output_path, du_output)

    log.info(f"Saved: {output_path}")

    # Find subdirectories larger than threshold
    min_size_bytes = min_size_gb * 1024**3
    large_subdirs = []

    for line in du_output.strip().split('\n'):
        parts = line.strip().split('\t')
        if len(parts) != 2:
            continue

        size_str, path = parts

        if is_excluded_path(path):
            continue

        if os.path.normpath(path) == os.path.normpath(directory):
            continue

        try:
            match = re.match(r'([0-9.]+)([KMGT]?)', size_str)
            if match:
                size_value, unit = match.groups()
                size_str_parsed = f"{size_value}{unit}"
                size_bytes = parse_size(size_str_parsed)

                if size_bytes >= min_size_bytes and os.path.isdir(path):
                    large_subdirs.append(path)
                    with _print_lock:
                        print(f"  Queuing large subdirectory: {path} ({size_str_parsed})")
        except (ValueError, TypeError) as e:
            if not quiet:
                log.debug(f"Error parsing size for {path}: {e}")

    return large_subdirs


def run_analysis(directory, output_base, base_directory, min_size_gb=2,
                 use_sudo=False, quiet=False, timeout_seconds=300, max_workers=4):
    """
    BFS-style analysis: process directories level by level using a thread pool.
    Avoids deadlock by never submitting to the pool from within a pool worker.
    """
    queue = [directory]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while queue:
            log.info(f"Processing batch of {len(queue)} directories")
            with _print_lock:
                print(f"\n--- Processing {len(queue)} directories in parallel ---")

            # Submit all directories in the current batch
            futures = {}
            for d in queue:
                future = executor.submit(
                    analyze_single_directory, d, output_base, base_directory,
                    min_size_gb, use_sudo, quiet, timeout_seconds
                )
                futures[future] = d

            # Collect results: all large subdirs become the next batch
            next_queue = []
            for future in as_completed(futures):
                d = futures[future]
                try:
                    large_subdirs = future.result()
                    next_queue.extend(large_subdirs)
                except Exception as e:
                    log.error(f"Error analyzing {d}: {e}")

            queue = next_queue

def main():
    global _stats, _executor

    parser = argparse.ArgumentParser(description='Analyze disk usage recursively.')
    parser.add_argument('directory', nargs='?', default=os.path.expanduser('~'),
                        help='Base directory to analyze (default: user home)')
    parser.add_argument('--output', '-o', default='./output',
                        help='Base output directory (default: ./output)')
    parser.add_argument('--min-size', '-m', type=float, default=2.0,
                        help='Minimum size in GB to process subdirectories (default: 2.0)')
    parser.add_argument('--sudo', '-s', action='store_true',
                        help='Use sudo for du commands (access more directories)')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='Suppress error messages from du command')
    parser.add_argument('--debug', '-d', action='store_true',
                        help='Enable debug output')
    parser.add_argument('--workers', '-w', type=int, default=4,
                        help='Number of parallel workers (default: 4)')
    parser.add_argument('--timeout', '-t', type=int, default=300,
                        help='Timeout in seconds per du command (default: 300)')
    parser.add_argument('--log-file', default=None,
                        help='Log file path (default: disk_analyzer.log in output dir)')

    args = parser.parse_args()

    # Generate timestamp for this run
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    # Convert to absolute paths
    directory = os.path.abspath(args.directory)
    base_output = os.path.abspath(args.output)
    output_base = os.path.join(base_output, timestamp)

    # Create output directory
    os.makedirs(output_base, exist_ok=True)

    # Setup logging
    log_file = args.log_file or os.path.join(output_base, "disk_analyzer.log")
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler() if args.debug else logging.NullHandler(),
        ],
    )
    log.info(f"Starting analysis: directory={directory}, workers={args.workers}, "
             f"timeout={args.timeout}s, min_size={args.min_size}GB")
    log.info(f"Excluded paths: {[str(p) for p in EXCLUDED_PATHS]}")

    # Display permission information
    print("\nDisk Analyzer")
    print("------------------------------------")
    print(f"Target:     {directory}")
    print(f"Output:     {output_base}")
    print(f"Workers:    {args.workers}")
    print(f"Timeout:    {args.timeout}s per directory")
    print(f"Min size:   {args.min_size}GB")
    print(f"Log file:   {log_file}")
    if args.sudo:
        print("Mode:       sudo (may prompt for password)")
    print(f"Excluded:   {len(EXCLUDED_PATHS)} paths")
    print("------------------------------------\n")

    # Initialize stats
    _stats = AnalysisStats()

    run_analysis(directory, output_base, directory, args.min_size,
                 args.sudo, args.quiet, args.timeout, args.workers)

    print(f"\nResults saved to {output_base}")
    print(_stats.summary())
    log.info(_stats.summary())

if __name__ == "__main__":
    main() 
