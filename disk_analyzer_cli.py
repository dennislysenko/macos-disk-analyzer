#!/usr/bin/env python3

import os
import sys
import argparse
import curses

CONFIG_DIR = os.path.expanduser("~/.config/disk-analyzer")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.toml")


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
        elif key == ord("q"):
            return
        elif key == ord("1"):
            run_scan_tui(stdscr, config)
        elif key == ord("2"):
            run_browse_tui(stdscr, config)


def run_scan_tui(stdscr, config):
    """Fullscreen curses scan: input, progress bar, scrolling log, cancel support."""
    import datetime
    import logging
    import threading
    import time
    import io
    from disk_analyzer import run_analysis, AnalysisStats

    curses.curs_set(1)
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    default_dir = config.get("default_directory", os.path.expanduser("~"))
    default_min = config.get("min_size_gb", "2.0")

    stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
    stdscr.addstr(1, 2, "New Scan")
    stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
    stdscr.addstr(2, 2, "─" * min(40, width - 4))

    # Directory input
    stdscr.addstr(4, 2, f"Directory [{default_dir}]: ")
    stdscr.refresh()
    curses.echo()
    dir_input = stdscr.getstr(4, 2 + len(f"Directory [{default_dir}]: "), 256).decode().strip()
    directory = dir_input if dir_input else default_dir

    # Min size input
    stdscr.addstr(6, 2, f"Min size GB [{default_min}]: ")
    stdscr.refresh()
    size_input = stdscr.getstr(6, 2 + len(f"Min size GB [{default_min}]: "), 20).decode().strip()
    curses.noecho()
    curses.curs_set(0)

    try:
        min_size = float(size_input) if size_input else float(default_min)
    except ValueError:
        min_size = float(default_min)

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

    workers = int(config.get("workers", 4))
    timeout = int(config.get("timeout", 300))

    # Count top-level dirs for progress estimate
    try:
        top_level = [e for e in os.listdir(directory)
                     if os.path.isdir(os.path.join(directory, e)) and not e.startswith('.')]
        total_top = len(top_level)
    except OSError:
        total_top = 0

    import disk_analyzer
    disk_analyzer._stats = AnalysisStats()
    stats = disk_analyzer._stats

    # State shared between scan thread and UI
    log_lines = []
    log_lock = threading.Lock()
    scan_done = threading.Event()
    scan_cancelled = threading.Event()
    BAR_WIDTH = max(20, width - 30)
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

        # Progress bar
        analyzed = stats.dirs_analyzed
        elapsed = time.monotonic() - stats.start_time
        pct = min(0.95, analyzed / (analyzed + expected))
        filled = int(BAR_WIDTH * pct)
        bar = "█" * filled + "░" * (BAR_WIDTH - filled)
        bar_line = f"[{bar}] {int(pct*100)}%  {analyzed} dirs | {elapsed:.0f}s"

        stdscr.addstr(3, 2, bar_line[:width - 4])

        # Divider
        stdscr.addstr(4, 2, "─" * min(width - 4, 60))

        # Scrolling log (fill available space)
        log_start = 5
        log_height = height - log_start - 2  # leave room for footer
        with log_lock:
            visible = log_lines[-(log_height):] if log_height > 0 else []
        for i, line in enumerate(visible):
            y = log_start + i
            if y >= height - 2:
                break
            try:
                stdscr.addstr(y, 2, line[:width - 4])
            except curses.error:
                pass

        # Footer
        footer = "c: Cancel scan"
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

        if key == ord("c"):
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

    # Scan complete — show final state
    thread.join()
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


def main():
    parser = argparse.ArgumentParser(
        prog="disk-analyzer",
        description="Analyze and explore disk usage.",
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
                             help="Parallel workers (default: 4)")
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
    else:
        # No subcommand → launch TUI main menu
        try:
            curses.wrapper(tui_main_menu)
        except KeyboardInterrupt:
            pass
        print("Thank you for using Disk Analyzer!")


if __name__ == "__main__":
    main()
