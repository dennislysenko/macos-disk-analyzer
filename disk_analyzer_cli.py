#!/usr/bin/env python3

import os
import sys
import argparse
import curses

import json

CONFIG_DIR = os.path.expanduser("~/.config/disk-analyzer")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.toml")
SCAN_HISTORY_FILE = ".scan_history.json"


def load_config():
    """Load config from ~/.config/disk-analyzer/config.toml if it exists."""
    config = {}
    if not os.path.exists(CONFIG_FILE):
        return config

    try:
        # Python 3.11+ has tomllib
        import tomllib
        with open(CONFIG_FILE, "rb") as f:
            config = tomllib.load(f)
    except ImportError:
        # Fallback: simple key=value parsing for older Python
        with open(CONFIG_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    config[key] = value
    return config


def get_api_key(config):
    """Get API key from env var (priority) or config file."""
    return os.environ.get("DISK_ANALYZER_API_KEY", config.get("api_key", ""))


def get_output_dir(config):
    """Get output directory from config or default."""
    return config.get("output_dir", "./output")


def load_scan_history(output_dir):
    """Load prior scan metadata for ETA heuristics."""
    path = os.path.join(output_dir, SCAN_HISTORY_FILE)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_scan_history(output_dir, directory, total_dirs, total_time):
    """Append scan metadata for future ETA estimates."""
    path = os.path.join(output_dir, SCAN_HISTORY_FILE)
    history = load_scan_history(output_dir)
    history.append({
        "directory": directory,
        "total_dirs": total_dirs,
        "total_time": round(total_time, 1),
    })
    # Keep last 20 entries
    history = history[-20:]
    try:
        with open(path, "w") as f:
            json.dump(history, f, indent=2)
    except OSError:
        pass


def estimate_from_history(output_dir, directory):
    """Return (expected_dirs, has_history) based on prior scans of the same directory."""
    history = load_scan_history(output_dir)
    # Find prior scans of the same directory
    matching = [h for h in history if h.get("directory") == directory]
    if matching:
        # Use average of matching scans
        avg_dirs = sum(h["total_dirs"] for h in matching) / len(matching)
        return int(avg_dirs), True
    return None, False


def format_eta(seconds):
    """Format seconds into a human-readable ETA string."""
    if seconds < 0:
        return "??:??"
    m, s = divmod(int(seconds), 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}h{m:02d}m"
    return f"{m}m{s:02d}s"


def tui_main_menu(stdscr):
    """Curses-based main menu: Scan, Browse, Quit."""
    curses.curs_set(0)
    curses.use_default_colors()

    # Init color pairs
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)
    curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLUE)

    config = load_config()
    selected = 0
    menu_items = [
        ("Scan", "Run a new disk usage analysis"),
        ("Browse", "Browse previous analysis results"),
        ("Recommend", "Get cleanup recommendations"),
        ("Quit", "Exit disk-analyzer"),
    ]

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # Title
        title = "Disk Analyzer"
        subtitle = "Analyze and explore disk usage"
        stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(1, max(0, (width - len(title)) // 2), title)
        stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
        stdscr.attron(curses.color_pair(1))
        stdscr.addstr(2, max(0, (width - len(subtitle)) // 2), subtitle)
        stdscr.attroff(curses.color_pair(1))

        # Divider
        divider = "─" * min(40, width - 2)
        stdscr.addstr(4, max(0, (width - len(divider)) // 2), divider)

        # Menu items
        for i, (label, desc) in enumerate(menu_items):
            y = 6 + i * 2
            if y >= height - 2:
                break
            if i == selected:
                stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
                line = f"  ▸ {label:<10} {desc}  "
                stdscr.addstr(y, max(0, (width - len(line)) // 2), line)
                stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)
            else:
                stdscr.attron(curses.color_pair(2))
                line = f"    {label:<10} {desc}"
                stdscr.addstr(y, max(0, (width - len(line)) // 2), line)
                stdscr.attroff(curses.color_pair(2))

        # Footer
        footer = "↑/↓: Navigate  Enter: Select  q: Quit"
        if height > 14:
            stdscr.attron(curses.color_pair(3))
            stdscr.addstr(height - 2, max(0, (width - len(footer)) // 2), footer)
            stdscr.attroff(curses.color_pair(3))

        stdscr.refresh()

        key = stdscr.getch()
        if key == curses.KEY_UP:
            selected = (selected - 1) % len(menu_items)
        elif key == curses.KEY_DOWN:
            selected = (selected + 1) % len(menu_items)
        elif key in (curses.KEY_ENTER, 10, 13):
            choice = menu_items[selected][0]
            if choice == "Quit":
                return
            elif choice == "Scan":
                run_scan_tui(stdscr, config)
            elif choice == "Browse":
                run_browse_tui(stdscr, config)
            elif choice == "Recommend":
                run_recommend_tui(stdscr, config)
        elif key == ord("q"):
            return
        elif key == ord("1"):
            run_scan_tui(stdscr, config)
        elif key == ord("2"):
            run_browse_tui(stdscr, config)
        elif key == ord("3"):
            run_recommend_tui(stdscr, config)


def run_scan_tui(stdscr, config):
    """Fullscreen curses scan: input, progress bar, scrolling log, cancel support."""
    import datetime
    import logging
    import threading
    import time
    import io
    from disk_analyzer import run_analysis, AnalysisStats

    curses.curs_set(0)

    home_dir = os.path.expanduser("~")
    custom_dir = config.get("default_directory", home_dir)

    # --- Step 1: Directory selection ---
    dir_options = [
        ("Entire drive", "/"),
        ("Home folder", home_dir),
        ("Custom path", None),
    ]
    dir_selected = 0

    MIN_SIZES = [0.5, 1.0, 2.0, 5.0, 10.0]
    default_min = float(config.get("min_size_gb", "2.0"))
    try:
        size_selected = MIN_SIZES.index(default_min)
    except ValueError:
        size_selected = 2  # default to 2.0

    step = 0  # 0 = directory, 1 = min size, 2 = done

    while step < 2:
        height, width = stdscr.getmaxyx()
        stdscr.erase()

        # Title
        stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(1, 2, "New Scan")
        stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(2, 2, "─" * min(40, width - 4))

        if step == 0:
            # Directory selection
            stdscr.addstr(4, 2, "What to scan:")

            for i, (label, path) in enumerate(dir_options):
                y = 6 + i
                if y >= height - 3:
                    break
                display = f"{label}  ({path})" if path else label
                if i == dir_selected:
                    stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
                    stdscr.addstr(y, 4, f"▸ {display}"[:width - 6])
                    stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)
                else:
                    stdscr.addstr(y, 4, f"  {display}"[:width - 6])

            try:
                stdscr.attron(curses.color_pair(3))
                stdscr.addstr(height - 2, 2, "↑/↓: Select  Enter: Confirm  q: Cancel")
                stdscr.attroff(curses.color_pair(3))
            except curses.error:
                pass

        elif step == 1:
            # Min size selection
            stdscr.addstr(4, 2, "Minimum directory size to recurse into:")
            stdscr.attron(curses.color_pair(3))
            stdscr.addstr(5, 2, "Smaller = more detail but slower scan"[:width - 4])
            stdscr.addstr(6, 2, "Larger  = faster scan, only big folders"[:width - 4])
            stdscr.attroff(curses.color_pair(3))

            for i, size in enumerate(MIN_SIZES):
                y = 8 + i
                if y >= height - 3:
                    break
                label = f"{size}GB"
                if size == 0.5:
                    hint = "very detailed, slowest"
                elif size == 1.0:
                    hint = "detailed"
                elif size == 2.0:
                    hint = "balanced (default)"
                elif size == 5.0:
                    hint = "fast, big folders only"
                else:
                    hint = "fastest, very large only"
                display = f"{label:<8} {hint}"
                if i == size_selected:
                    stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
                    stdscr.addstr(y, 4, f"▸ {display}"[:width - 6])
                    stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)
                else:
                    stdscr.addstr(y, 4, f"  {display}"[:width - 6])

            try:
                stdscr.attron(curses.color_pair(3))
                stdscr.addstr(height - 2, 2, "↑/↓: Select  Enter: Confirm  Backspace: Back  q: Cancel")
                stdscr.attroff(curses.color_pair(3))
            except curses.error:
                pass

        stdscr.refresh()
        key = stdscr.getch()

        if key == ord("q"):
            return
        elif key in (curses.KEY_BACKSPACE, 127, 8) and step > 0:
            step -= 1
        elif key == curses.KEY_UP:
            if step == 0:
                dir_selected = (dir_selected - 1) % len(dir_options)
            else:
                size_selected = (size_selected - 1) % len(MIN_SIZES)
        elif key == curses.KEY_DOWN:
            if step == 0:
                dir_selected = (dir_selected + 1) % len(dir_options)
            else:
                size_selected = (size_selected + 1) % len(MIN_SIZES)
        elif key in (curses.KEY_ENTER, 10, 13):
            if step == 0 and dir_options[dir_selected][1] is None:
                # Custom path — need text input
                stdscr.addstr(10, 4, "Path: ")
                curses.curs_set(1)
                curses.echo()
                path_input = stdscr.getstr(10, 10, 256).decode().strip()
                curses.noecho()
                curses.curs_set(0)
                if path_input:
                    custom_dir = path_input
                    dir_options[2] = ("Custom path", custom_dir)
                step = 1
            else:
                step += 1

    directory = dir_options[dir_selected][1]
    min_size = MIN_SIZES[size_selected]

    output_dir = os.path.abspath(get_output_dir(config))
    directory = os.path.abspath(os.path.expanduser(directory))

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_base = os.path.join(output_dir, timestamp)
    os.makedirs(output_base, exist_ok=True)

    log_file = os.path.join(output_base, "disk_analyzer.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.NullHandler(),
        ],
        force=True,
    )

    workers = int(config.get("workers", 8))
    timeout = int(config.get("timeout", 300))

    # Count top-level dirs for progress estimate
    try:
        top_level = [e for e in os.listdir(directory)
                     if os.path.isdir(os.path.join(directory, e)) and not e.startswith('.')]
        total_top = len(top_level)
    except OSError:
        total_top = 0

    SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    spin_idx = 0

    import disk_analyzer
    disk_analyzer._stats = AnalysisStats()
    disk_analyzer._stats.num_workers = workers
    stats = disk_analyzer._stats

    # State shared between scan thread and UI
    log_lines = []
    log_lock = threading.Lock()
    scan_done = threading.Event()
    scan_cancelled = threading.Event()
    BAR_WIDTH = max(20, width - 30)
    hist_expected, has_history = estimate_from_history(output_dir, directory)
    if hist_expected:
        expected = hist_expected
    else:
        expected = max(total_top * 3, 10)

    # Intercept stdout to capture log lines from disk_analyzer
    real_stdout = sys.stdout

    class LogCapture:
        def __init__(self):
            self._buf = ""
        def write(self, text):
            self._buf += text
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                if line.strip():
                    with log_lock:
                        log_lines.append(line.strip())
        def flush(self):
            if self._buf.strip():
                with log_lock:
                    log_lines.append(self._buf.strip())
                self._buf = ""
        def __getattr__(self, name):
            return getattr(real_stdout, name)

    # Run scan in background thread
    def scan_thread():
        sys.stdout = LogCapture()
        try:
            run_analysis(directory, output_base, directory, min_size,
                         False, False, timeout, workers)
        finally:
            sys.stdout = real_stdout
            scan_done.set()

    thread = threading.Thread(target=scan_thread, daemon=True)
    thread.start()

    # Fullscreen progress UI
    stdscr.nodelay(True)  # non-blocking getch for cancel detection
    cancelled = False
    show_workers = True  # True = worker view, False = log view

    while not scan_done.is_set():
        height, width = stdscr.getmaxyx()
        stdscr.erase()

        # Title
        stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(0, 2, "Scanning")
        stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

        # Info line
        info = f"Target: {directory}  |  Min: {min_size}GB  |  Workers: {workers}"
        stdscr.addstr(1, 2, info[:width - 4])

        # Progress bar with ETA
        analyzed = stats.dirs_analyzed
        elapsed = time.monotonic() - stats.start_time
        pct = min(0.95, analyzed / (analyzed + expected))
        filled = int(BAR_WIDTH * pct)
        bar = "█" * filled + "░" * (BAR_WIDTH - filled)

        # ETA calculation
        if analyzed > 0:
            rate = elapsed / analyzed  # seconds per dir
            remaining_dirs = max(0, expected - analyzed)
            eta_secs = rate * remaining_dirs
            eta_str = f"ETA {format_eta(eta_secs)}"
        else:
            eta_str = "ETA --:--"

        bar_line = f"[{bar}] {int(pct*100)}%  {analyzed} dirs | {elapsed:.0f}s"
        stdscr.addstr(3, 2, bar_line[:width - 4])

        # ETA on its own line
        eta_note = f"  {eta_str}" + ("  (rough est. — improves after first scan)" if not has_history else "")
        try:
            stdscr.attron(curses.color_pair(3))
            stdscr.addstr(4, 2, eta_note[:width - 4])
            stdscr.attroff(curses.color_pair(3))
        except curses.error:
            pass

        # Divider + view label
        view_label = " Workers " if show_workers else " Log "
        divider_width = min(width - 4, 60)
        divider = "─" * divider_width
        label_pos = (divider_width - len(view_label)) // 2
        divider = divider[:label_pos] + view_label + divider[label_pos + len(view_label):]
        stdscr.addstr(5, 2, divider)

        content_start = 6
        content_height = height - content_start - 2

        if show_workers:
            # Per-worker stable numbered view
            worker_status = stats.get_worker_status()
            for i, (wnum, wdir, dur) in enumerate(worker_status):
                y = content_start + i
                if y >= height - 2:
                    break
                try:
                    label = f"  Worker {wnum:<2}"
                    stdscr.addstr(y, 2, label)
                    if wdir:
                        # Shorten path relative to scan root
                        display_path = wdir
                        if wdir.startswith(directory):
                            rel = wdir[len(directory):]
                            if directory == "/":
                                display_path = wdir  # scanning root, show absolute
                            elif rel:
                                display_path = rel.lstrip("/")
                            else:
                                display_path = os.path.basename(directory)
                        stdscr.attron(curses.color_pair(2))
                        stdscr.addstr(y, 14, f"{dur:5.1f}s")
                        stdscr.attroff(curses.color_pair(2))
                        stdscr.addstr(y, 21, f" {display_path}"[:width - 22])
                    else:
                        stdscr.attron(curses.color_pair(3))
                        stdscr.addstr(y, 14, f"{SPINNER[spin_idx % len(SPINNER)]} idle")
                        stdscr.attroff(curses.color_pair(3))
                except curses.error:
                    pass
        else:
            # Chronological log view
            with log_lock:
                visible = log_lines[-(content_height):] if content_height > 0 else []
            for i, line in enumerate(visible):
                y = content_start + i
                if y >= height - 2:
                    break
                try:
                    stdscr.addstr(y, 2, line[:width - 4])
                except curses.error:
                    pass

        # Footer
        footer = "Tab: Toggle view  |  c: Cancel scan"
        try:
            stdscr.attron(curses.color_pair(3))
            stdscr.addstr(height - 1, 2, footer)
            stdscr.attroff(curses.color_pair(3))
        except curses.error:
            pass

        stdscr.refresh()

        # Check for cancel key
        try:
            key = stdscr.getch()
        except curses.error:
            key = -1

        if key == ord("\t"):
            show_workers = not show_workers
        elif key == ord("c"):
            # Confirm cancel
            stdscr.attron(curses.color_pair(3) | curses.A_BOLD)
            try:
                stdscr.addstr(height - 1, 2, "Cancel scan? (y/n)".ljust(width - 4))
            except curses.error:
                pass
            stdscr.attroff(curses.color_pair(3) | curses.A_BOLD)
            stdscr.refresh()

            # Wait for confirmation (blocking)
            stdscr.nodelay(False)
            confirm = stdscr.getch()
            stdscr.nodelay(True)

            if confirm == ord("y"):
                scan_cancelled.set()
                cancelled = True
                # Force-kill running subprocesses by shutting down the executor
                if disk_analyzer._executor:
                    disk_analyzer._executor.shutdown(wait=False, cancel_futures=True)
                break

        spin_idx += 1
        curses.napms(200)  # ~5 fps refresh

    stdscr.nodelay(False)

    if cancelled:
        # Show cancelled state briefly
        stdscr.erase()
        stdscr.attron(curses.color_pair(3) | curses.A_BOLD)
        stdscr.addstr(height // 2, max(0, (width - 20) // 2), "Scan cancelled.")
        stdscr.attroff(curses.color_pair(3) | curses.A_BOLD)
        stdscr.addstr(height // 2 + 1, max(0, (width - 30) // 2), "Press any key to return to menu")
        stdscr.refresh()
        stdscr.getch()
        return

    # Scan complete — save history for future ETA estimates
    thread.join()
    total_time = time.monotonic() - stats.start_time
    save_scan_history(output_dir, directory, stats.dirs_analyzed, total_time)
    height, width = stdscr.getmaxyx()
    stdscr.erase()

    stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
    stdscr.addstr(1, 2, "Scan Complete")
    stdscr.attroff(curses.color_pair(2) | curses.A_BOLD)

    # Final progress bar at 100%
    bar = "█" * BAR_WIDTH
    elapsed = time.monotonic() - stats.start_time
    stdscr.addstr(3, 2, f"[{bar}] 100%  {stats.dirs_analyzed} dirs | {elapsed:.0f}s")

    stdscr.addstr(5, 2, f"Results saved to {output_base}")
    stdscr.addstr(6, 2, f"Directories analyzed: {stats.dirs_analyzed}")
    stdscr.addstr(7, 2, f"Directories skipped:  {stats.dirs_skipped}")
    stdscr.addstr(8, 2, f"Total time: {elapsed:.1f}s")

    if stats.slowest_dirs:
        stdscr.addstr(10, 2, "Slowest directories:")
        for i, (dur, path) in enumerate(stats.slowest_dirs[:5]):
            if 11 + i >= height - 3:
                break
            try:
                stdscr.addstr(11 + i, 4, f"{dur:5.1f}s  {path}"[:width - 6])
            except curses.error:
                pass

    stdscr.attron(curses.color_pair(3))
    try:
        stdscr.addstr(height - 2, 2, "Enter: Browse results  |  q: Return to menu")
    except curses.error:
        pass
    stdscr.attroff(curses.color_pair(3))
    stdscr.refresh()

    # Wait for user choice
    while True:
        key = stdscr.getch()
        if key in (curses.KEY_ENTER, 10, 13):
            from browser_tui import OutputBrowser
            browser = OutputBrowser(get_output_dir(config))
            browser.current_timestamp = timestamp
            browser.timestamp_dir = timestamp
            browser.browser(stdscr)
            return
        elif key == ord("q"):
            return


def run_browse_tui(stdscr, config):
    """Launch the existing TUI browser."""
    from browser_tui import OutputBrowser

    output_dir = get_output_dir(config)
    browser = OutputBrowser(output_dir)
    browser.browser(stdscr)


def run_recommend_tui(stdscr, config):
    """Show cleanup recommendations for a previous scan."""
    from browser_tui import OutputBrowser
    from cleanup_recommendations import generate_recommendations, show_recommendations

    output_dir = get_output_dir(config)
    browser = OutputBrowser(output_dir)
    if not browser.display_timestamp_selector(stdscr):
        return
    scan_dir = os.path.join(output_dir, browser.timestamp_dir)
    recommendations = generate_recommendations(scan_dir, browser.current_path)
    show_recommendations(stdscr, recommendations, scan_dir=scan_dir, root_path=browser.current_path)


def cmd_scan(args):
    """Subcommand: run a scan from CLI."""
    # Delegate to the existing main() in disk_analyzer
    sys.argv = ["disk_analyzer"]
    if args.directory:
        sys.argv.append(args.directory)
    if args.output:
        sys.argv.extend(["--output", args.output])
    if args.min_size is not None:
        sys.argv.extend(["--min-size", str(args.min_size)])
    if args.sudo:
        sys.argv.append("--sudo")
    if args.quiet:
        sys.argv.append("--quiet")
    if args.debug:
        sys.argv.append("--debug")
    if args.workers is not None:
        sys.argv.extend(["--workers", str(args.workers)])
    if args.timeout is not None:
        sys.argv.extend(["--timeout", str(args.timeout)])

    from disk_analyzer import main as analyzer_main
    analyzer_main()


def cmd_browse(args):
    """Subcommand: launch the browser."""
    output_dir = args.output or get_output_dir(load_config())

    if args.gui:
        try:
            from browser_gui import DiskAnalyzerGUI
            app = DiskAnalyzerGUI(output_dir)
            app.run()
        except ImportError:
            print("Error: GUI requires matplotlib and tkinter.", file=sys.stderr)
            print("  pip install matplotlib", file=sys.stderr)
            sys.exit(1)
    else:
        from browser_tui import OutputBrowser
        browser = OutputBrowser(output_dir)
        try:
            curses.wrapper(browser.browser)
        except KeyboardInterrupt:
            pass


def run_latest_recommendations(stdscr, config):
    """Short-circuit to recommendations for the most recent scan."""
    from browser_tui import OutputBrowser
    from cleanup_recommendations import generate_recommendations, show_recommendations

    output_dir = get_output_dir(config)
    browser = OutputBrowser(output_dir)
    timestamps = browser.load_timestamps()
    if not timestamps:
        stdscr.clear()
        stdscr.addstr(1, 2, "No scans found.", curses.A_BOLD)
        stdscr.addstr(3, 2, "Run a scan first. Press any key to exit.")
        stdscr.refresh()
        stdscr.getch()
        return

    latest_dir = timestamps[0][0]
    browser.timestamp_dir = latest_dir
    browser.current_timestamp = latest_dir
    disk_usage = browser.load_disk_usage_file(latest_dir)
    if not disk_usage:
        stdscr.clear()
        stdscr.addstr(1, 2, "Latest scan has no disk_usage.txt.", curses.A_BOLD)
        stdscr.addstr(3, 2, "Press any key to exit.")
        stdscr.refresh()
        stdscr.getch()
        return

    root_path = disk_usage[0][1]
    browser.current_path = root_path
    browser.root_path = root_path

    scan_dir = os.path.join(output_dir, latest_dir)
    stdscr.clear()
    try:
        stdscr.addstr(1, 2, "Loading recommendations...", curses.A_BOLD)
        stdscr.addstr(2, 2, "(first open of a new scan reads the full snapshot;", curses.A_DIM)
        stdscr.addstr(3, 2, " subsequent opens are instant.)", curses.A_DIM)
    except curses.error:
        pass
    stdscr.refresh()
    recommendations = generate_recommendations(scan_dir, root_path)
    show_recommendations(stdscr, recommendations, scan_dir=scan_dir, root_path=root_path)


def main():
    parser = argparse.ArgumentParser(
        prog="disk-analyzer",
        description="Analyze and explore disk usage.",
    )
    parser.add_argument(
        "--latest-recommendations",
        action="store_true",
        help="Jump straight to the opportunity ladder for the most recent scan.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # scan subcommand
    scan_parser = subparsers.add_parser("scan", help="Run a new disk usage analysis")
    scan_parser.add_argument("directory", nargs="?", default=None,
                             help="Directory to analyze (default: home)")
    scan_parser.add_argument("--output", "-o", default=None,
                             help="Output directory (default: ./output)")
    scan_parser.add_argument("--min-size", "-m", type=float, default=None,
                             help="Minimum size in GB (default: 2.0)")
    scan_parser.add_argument("--sudo", "-s", action="store_true",
                             help="Use sudo for du commands")
    scan_parser.add_argument("--quiet", "-q", action="store_true",
                             help="Suppress error messages")
    scan_parser.add_argument("--debug", "-d", action="store_true",
                             help="Enable debug output")
    scan_parser.add_argument("--workers", "-w", type=int, default=None,
                             help="Parallel workers (default: 8)")
    scan_parser.add_argument("--timeout", "-t", type=int, default=None,
                             help="Timeout per directory in seconds (default: 300)")

    # browse subcommand
    browse_parser = subparsers.add_parser("browse", help="Browse analysis results")
    browse_parser.add_argument("--output", "-o", default=None,
                               help="Output directory (default: ./output)")
    browse_parser.add_argument("--gui", "-g", action="store_true",
                               help="Use GUI browser instead of TUI")

    args = parser.parse_args()

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "browse":
        cmd_browse(args)
    elif args.latest_recommendations:
        config = load_config()
        try:
            curses.wrapper(run_latest_recommendations, config)
        except KeyboardInterrupt:
            pass
    else:
        # No subcommand → launch TUI main menu
        try:
            curses.wrapper(tui_main_menu)
        except KeyboardInterrupt:
            pass
        print("Thank you for using Disk Analyzer!")


if __name__ == "__main__":
    main()
