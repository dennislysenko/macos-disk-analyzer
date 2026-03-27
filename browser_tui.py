#!/usr/bin/env python3

import os
import datetime
import curses
import argparse
import subprocess
import threading
import time

from disk_analyzer import run_du_command, filter_excluded_entries

# Color pair IDs for percentage thresholds
COLOR_PCT_1 = 1   # 2.5-5%
COLOR_PCT_2 = 2   # 5-10%
COLOR_PCT_3 = 3   # 10-15%
COLOR_PCT_4 = 4   # 15-20%
COLOR_PCT_5 = 5   # 20-30%
COLOR_PCT_6 = 6   # 30-40%
COLOR_PCT_7 = 7   # 40-50%
COLOR_PCT_8 = 8   # 50%+
COLOR_SCAN = 9    # rescan progress

class OutputBrowser:
    def __init__(self, output_dir="./output"):
        self.output_dir = os.path.abspath(output_dir)
        self.current_timestamp = None
        self.current_path = None
        self.timestamp_dir = None
        self.disk_usage_data = []
        self.current_entries = []
        self.selected_idx = 0
        self.scroll_offset = 0
        self.max_display_items = 0
        self.root_size_bytes = 0
        # Set up log file path in the output directory
        self.log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_debug.log")
        # Rescan state
        self._scan_thread = None
        self._scan_result = None  # will hold (du_output, target_path) when done
        self._scan_start = None
        self._scan_cancel = threading.Event()
        self._scan_durations = {}  # path -> last scan duration in seconds
        self._scan_target_path = None  # the path being rescanned
        self._scan_target_idx = None  # index in options list being rescanned
        
    def log(self, message):
        """Write a debug message to the log file with timestamp"""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        with open(self.log_file, "a") as f:
            f.write(f"[{timestamp}] {message}\n")
        
    def parse_size_to_bytes(self, size_str):
        """Convert size string with units (like '2.5G') to bytes"""
        if not size_str or size_str == "?":
            return 0
        size_str = size_str.strip()
        multiplier = {'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4, 'B': 1}
        try:
            if size_str[-1].upper() in multiplier:
                return float(size_str[:-1]) * multiplier[size_str[-1].upper()]
            else:
                return float(size_str)
        except (ValueError, IndexError):
            return 0

    def load_timestamps(self):
        """Load all timestamp directories from the output folder"""
        timestamps = []
        
        if not os.path.exists(self.output_dir):
            return []
            
        # Get all subdirectories in the output folder
        dirs = [d for d in os.listdir(self.output_dir) 
                if os.path.isdir(os.path.join(self.output_dir, d))]
        
        # Filter and convert timestamp directories
        for dir_name in dirs:
            try:
                # Try to parse the timestamp format
                timestamp = datetime.datetime.strptime(dir_name, "%Y-%m-%d_%H-%M-%S")
                timestamps.append((dir_name, timestamp))
            except ValueError:
                # Skip directories that don't match our timestamp format
                continue
                
        # Sort by timestamp, newest first
        timestamps.sort(key=lambda x: x[1], reverse=True)
        return timestamps
        
    def format_timestamp(self, timestamp):
        """Format a timestamp in a human-readable format"""
        now = datetime.datetime.now()
        ts = timestamp
        
        # Check if it's today
        if ts.date() == now.date():
            return f"Today, {ts.strftime('%I:%M %p')}"
        # Check if it's yesterday
        elif ts.date() == (now - datetime.timedelta(days=1)).date():
            return f"Yesterday, {ts.strftime('%I:%M %p')}"
        # Otherwise, show the full date
        else:
            return ts.strftime("%b %d, %Y, %I:%M %p")
    
    def load_disk_usage_file(self, timestamp_dir):
        """Load the disk_usage.txt file for a timestamp directory"""
        disk_usage_path = os.path.join(self.output_dir, timestamp_dir, "disk_usage.txt")
        
        if not os.path.exists(disk_usage_path):
            return []
            
        data = []
        with open(disk_usage_path, 'r') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) == 2:
                    size, path = parts
                    data.append((size, path))
        
        return data
    
    def get_current_directory_info(self):
        """Get information about the current directory from disk_usage data"""
        size = "?"
        entries = []

        self.log(f"Getting current directory info for {self.current_path}")
        self.log(f"Disk usage data: {self.disk_usage_data}")
        
        # Get the current directory's size
        for entry_size, entry_path in self.disk_usage_data:
            if entry_path == self.current_path:
                size = entry_size
                break
        
        # Get direct children of the current directory
        for entry_size, entry_path in self.disk_usage_data:
            # Skip the directory itself
            if entry_path == self.current_path:
                continue
                
            # Check if this is a direct child
            parent_dir = os.path.dirname(entry_path)
            if parent_dir == self.current_path:
                dir_name = os.path.basename(entry_path)
                # Convert size to numeric value for sorting
                try:
                    numeric_size = float(entry_size.rstrip('KMGTB'))
                    # Apply multiplier based on unit
                    multiplier = {'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4, 'B': 1}
                    unit = entry_size[-1] if entry_size[-1] in multiplier else 'B'
                    numeric_size *= multiplier[unit]
                except ValueError:
                    numeric_size = 0
                entries.append((dir_name, entry_path, entry_size, numeric_size))
        
        # Sort by numeric size (largest first), then by name for equal sizes
        entries.sort(key=lambda x: (-x[3], x[0].lower()))
        
        return size, [(name, path, size, numeric) for name, path, size, numeric in entries]
            
    def display_timestamp_selector(self, stdscr):
        """Display a fullscreen menu to select a timestamp"""
        timestamps = self.load_timestamps()
        
        if not timestamps:
            self.show_message(stdscr, "No analysis runs found. Press any key to exit.")
            stdscr.getch()
            return False
            
        height, width = stdscr.getmaxyx()
        selected_idx = 0
        scroll_offset = 0
        
        # Calculate max display items (leave space for header and footer)
        max_display = height - 6
        
        while True:
            stdscr.clear()
            
            # Display header
            stdscr.addstr(0, 0, "Disk Usage Analysis Browser", curses.A_BOLD)
            stdscr.addstr(1, 0, "=" * (width - 1))
            stdscr.addstr(2, 0, "Available analysis runs (newest first):")
            
            # Display timestamps
            display_count = min(max_display, len(timestamps))
            for i in range(display_count):
                idx = i + scroll_offset
                if idx >= len(timestamps):
                    break
                    
                dir_name, timestamp = timestamps[idx]
                formatted_time = self.format_timestamp(timestamp)
                
                # Highlight selected item
                if idx == selected_idx:
                    attr = curses.A_REVERSE
                else:
                    attr = curses.A_NORMAL
                    
                # Display item (truncate if too long)
                if width > 10:  # Make sure we have enough space
                    display_text = f"{idx + 1}. {formatted_time}"[:width-2]
                    stdscr.addstr(3 + i, 0, display_text, attr)
            
            # Display footer
            footer_pos = height - 2
            stdscr.addstr(footer_pos, 0, "↑/↓: Move selection, Enter: Select, q: Quit", curses.A_BOLD)
            
            stdscr.refresh()
            
            # Handle key input
            key = stdscr.getch()
            
            if key == ord('q'):
                return False
            elif key == curses.KEY_UP:
                if selected_idx > 0:
                    selected_idx -= 1
                    # Scroll if needed
                    if selected_idx < scroll_offset:
                        scroll_offset = selected_idx
            elif key == curses.KEY_DOWN:
                if selected_idx < len(timestamps) - 1:
                    selected_idx += 1
                    # Scroll if needed
                    if selected_idx >= scroll_offset + max_display:
                        scroll_offset = selected_idx - max_display + 1
            elif key == curses.KEY_ENTER or key == 10 or key == 13:  # Enter key
                if 0 <= selected_idx < len(timestamps):
                    timestamp_dir, _ = timestamps[selected_idx]
                    
                    # Load the disk usage data
                    self.disk_usage_data = self.load_disk_usage_file(timestamp_dir)
                    if not self.disk_usage_data:
                        self.show_message(stdscr, "Could not load disk usage data. Press any key to continue.")
                        stdscr.getch()
                        continue
                    
                    # Set the current timestamp directory
                    self.timestamp_dir = timestamp_dir
                    
                    # Find the first directory (typically the base directory)
                    if self.disk_usage_data:
                        self.current_path = self.disk_usage_data[0][1]  # Path of the first entry
                        self.root_size_bytes = self.parse_size_to_bytes(self.disk_usage_data[0][0])
                        return True
        
        return False
    
    def show_message(self, stdscr, message):
        """Display a centered message on screen"""
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        
        # Split message into lines
        lines = message.split('\n')
        
        # Calculate starting y position to center the message
        start_y = max(0, (height - len(lines)) // 2)
        
        for i, line in enumerate(lines):
            # Calculate starting x position to center the line
            start_x = max(0, (width - len(line)) // 2)
            
            # Make sure we don't go beyond the screen
            if start_y + i < height:
                stdscr.addstr(start_y + i, start_x, line[:width-1])
        
        stdscr.refresh()
    
    def open_in_finder(self, path):
        """Open the specified path in Finder"""
        try:
            subprocess.run(['open', path])
            return True
        except Exception as e:
            self.log(f"Error opening Finder: {str(e)}")
            return False

    def _rescan_worker(self, target_path):
        """Background worker: run du on target_path and store the result."""
        self.log(f"Rescan started for: {target_path}")
        du_output = run_du_command(target_path, quiet=True)
        if self._scan_cancel.is_set():
            self.log("Rescan was cancelled")
            return
        if du_output:
            du_output = filter_excluded_entries(du_output)
        self._scan_result = (du_output, target_path)
        self.log(f"Rescan finished for: {target_path}")

    def start_rescan(self, target_path, target_idx=None):
        """Kick off a background rescan of a specific path."""
        if self._scan_thread and self._scan_thread.is_alive():
            return  # already scanning
        self._scan_result = None
        self._scan_cancel.clear()
        self._scan_start = time.monotonic()
        self._scan_target_path = target_path
        self._scan_target_idx = target_idx
        self._scan_thread = threading.Thread(
            target=self._rescan_worker,
            args=(target_path,),
            daemon=True,
        )
        self._scan_thread.start()

    def is_scanning(self):
        return self._scan_thread is not None and self._scan_thread.is_alive()

    def scan_elapsed(self):
        if self._scan_start is None:
            return 0.0
        return time.monotonic() - self._scan_start

    def _format_bytes_human(self, size_bytes):
        """Convert bytes to human-readable string matching du output format."""
        if size_bytes == 0:
            return "0B"
        units = [(1024**4, 'T'), (1024**3, 'G'), (1024**2, 'M'), (1024, 'K')]
        for threshold, unit in units:
            if size_bytes >= threshold:
                val = size_bytes / threshold
                if val >= 10:
                    return f"{val:.0f}{unit}"
                else:
                    return f"{val:.1f}{unit}"
        return f"{size_bytes:.0f}B"

    def _update_parent_disk_usage(self, target_path, new_total_size_str):
        """Update the parent directory's disk_usage.txt to reflect the new size of target_path.
        Then propagate upward recursively until we reach root_path."""
        parent_path = os.path.dirname(target_path)

        # Find the parent's disk_usage.txt
        parent_rel = os.path.relpath(parent_path, self.root_path)
        if parent_rel == ".":
            parent_file = os.path.join(self.output_dir, self.timestamp_dir, "disk_usage.txt")
        else:
            parent_file = os.path.join(self.output_dir, self.timestamp_dir, parent_rel, "disk_usage.txt")

        if not os.path.exists(parent_file):
            self.log(f"Parent disk_usage.txt not found: {parent_file}")
            return

        # Read parent file and update the line for target_path
        lines = []
        updated = False
        with open(parent_file, 'r') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) == 2 and os.path.normpath(parts[1]) == os.path.normpath(target_path):
                    lines.append(f"{new_total_size_str}\t{parts[1]}\n")
                    updated = True
                else:
                    lines.append(line)

        if not updated:
            self.log(f"Target path {target_path} not found in parent file {parent_file}")
            return

        # Re-sum the parent total: add up all children
        parent_total = 0
        for line in lines:
            parts = line.strip().split('\t')
            if len(parts) == 2:
                p = os.path.normpath(parts[1])
                if p != os.path.normpath(parent_path):
                    parent_total += self.parse_size_to_bytes(parts[0])

        # Update the parent's own total line
        new_parent_size_str = self._format_bytes_human(parent_total)
        final_lines = []
        for line in lines:
            parts = line.strip().split('\t')
            if len(parts) == 2 and os.path.normpath(parts[1]) == os.path.normpath(parent_path):
                final_lines.append(f"{new_parent_size_str}\t{parts[1]}\n")
            else:
                final_lines.append(line)

        with open(parent_file, 'w') as f:
            f.writelines(final_lines)
        self.log(f"Updated parent {parent_file}: {target_path} -> {new_total_size_str}, parent total -> {new_parent_size_str}")

        # If the current view is showing this parent's data, reload it
        if os.path.normpath(self.current_path) == os.path.normpath(parent_path):
            new_data = []
            for line in final_lines:
                parts = line.strip().split('\t')
                if len(parts) == 2:
                    new_data.append((parts[0], parts[1]))
            if new_data:
                self.disk_usage_data = new_data

        # Propagate upward
        if os.path.normpath(parent_path) != os.path.normpath(self.root_path):
            self._update_parent_disk_usage(parent_path, new_parent_size_str)
        else:
            # We've reached root — update root_size_bytes
            self.root_size_bytes = parent_total

    def apply_scan_result(self):
        """Apply completed rescan result: save to disk, update parents, reload browser."""
        if self._scan_result is None:
            return False
        du_output, target_path = self._scan_result
        self._scan_result = None
        self._scan_thread = None
        self._scan_target_idx = None

        if not du_output or not du_output.strip():
            self.log("Rescan produced no output")
            return False

        # Compute output path and save
        rel_path = os.path.relpath(target_path, self.root_path)
        if rel_path == ".":
            output_file = os.path.join(self.output_dir, self.timestamp_dir, "disk_usage.txt")
        else:
            output_dir = os.path.join(self.output_dir, self.timestamp_dir, rel_path)
            os.makedirs(output_dir, exist_ok=True)
            output_file = os.path.join(output_dir, "disk_usage.txt")

        with open(output_file, "w") as f:
            f.write(du_output)
        self.log(f"Rescan saved to: {output_file}")

        # Parse the new data to find the total size of the rescanned dir
        new_data = []
        new_total_size_str = None
        for line in du_output.strip().splitlines():
            parts = line.strip().split('\t')
            if len(parts) == 2:
                new_data.append((parts[0], parts[1]))
                if os.path.normpath(parts[1]) == os.path.normpath(target_path):
                    new_total_size_str = parts[0]

        # Update parent disk_usage.txt files up the chain
        if new_total_size_str and os.path.normpath(target_path) != os.path.normpath(self.root_path):
            self._update_parent_disk_usage(target_path, new_total_size_str)

        # If we rescanned the directory we're currently viewing, reload its data
        if os.path.normpath(target_path) == os.path.normpath(self.current_path):
            if new_data:
                self.disk_usage_data = new_data
                if target_path == self.root_path:
                    self.root_size_bytes = self.parse_size_to_bytes(new_data[0][0])
                self.log(f"Rescan loaded {len(new_data)} entries for current view")

        return True
    
    def _detect_dark_theme(self):
        """Detect if terminal has a dark background via COLORFGBG env var."""
        colorfgbg = os.environ.get('COLORFGBG', '')
        if ';' in colorfgbg:
            try:
                bg = int(colorfgbg.rsplit(';', 1)[1])
                # bg 0-6 = dark colors, 7+ = light colors
                return bg < 7
            except ValueError:
                pass
        # Default to dark theme (most common for terminal users)
        return True

    def _init_colors(self):
        """Initialize color pairs adapted to terminal theme."""
        curses.start_color()
        curses.use_default_colors()
        bg = -1  # transparent background, inherits terminal default

        if curses.COLORS >= 256:
            # 8-step palette: yellow -> yellow-orange -> orange -> red
            colors = [226, 220, 214, 208, 202, 196, 160, 124]
        else:
            colors = [
                curses.COLOR_YELLOW, curses.COLOR_YELLOW,
                curses.COLOR_YELLOW, curses.COLOR_RED,
                curses.COLOR_RED, curses.COLOR_RED,
                curses.COLOR_RED, curses.COLOR_RED,
            ]
        for i, c in enumerate(colors):
            curses.init_pair(i + 1, c, bg)

        # Scan progress color: cyan on 256-color, cyan on 8-color
        if curses.COLORS >= 256:
            curses.init_pair(COLOR_SCAN, 45, bg)  # bright cyan
        else:
            curses.init_pair(COLOR_SCAN, curses.COLOR_CYAN, bg)

    def _pct_color(self, pct):
        """Return the curses color pair attribute for a percentage value."""
        if pct >= 50:
            return curses.color_pair(COLOR_PCT_8) | curses.A_BOLD
        elif pct >= 40:
            return curses.color_pair(COLOR_PCT_7)
        elif pct >= 30:
            return curses.color_pair(COLOR_PCT_6)
        elif pct >= 20:
            return curses.color_pair(COLOR_PCT_5)
        elif pct >= 15:
            return curses.color_pair(COLOR_PCT_4)
        elif pct >= 10:
            return curses.color_pair(COLOR_PCT_3)
        elif pct >= 5:
            return curses.color_pair(COLOR_PCT_2)
        elif pct >= 2.5:
            return curses.color_pair(COLOR_PCT_1)
        else:
            return curses.A_NORMAL

    def browser(self, stdscr):
        """Main curses-based browser"""
        # Setup curses
        curses.curs_set(0)  # Hide cursor
        self._init_colors()
        stdscr.clear()
        stdscr.refresh()

        # Enable keypad (for arrow keys)
        stdscr.keypad(True)
        
        # Select timestamp
        if not self.display_timestamp_selector(stdscr):
            return
        
        # Start browsing
        # Remove history stack - we'll just use parent directories
        
        while True:
            # Get screen dimensions
            height, width = stdscr.getmaxyx()
            
            # Adjust max display items based on screen height
            self.max_display_items = height - 9
            
            # Get current directory information
            current_size, current_entries = self.get_current_directory_info()
            
            # Build options list with parent directory if not at root level
            options = []
            
            # Keep track of the initial root directory (from first timestamp selection)
            # This is used to detect if we're at the top level
            if not hasattr(self, 'root_path') and len(self.disk_usage_data) > 0:
                self.root_path = self.disk_usage_data[0][1]
                self.log(f"Setting root path to: {self.root_path}")
            
            # Compute current folder size in bytes for percentage calc
            current_size_bytes = self.parse_size_to_bytes(current_size)

            # Add parent directory entry if not at the root level
            if self.current_path != getattr(self, 'root_path', None):
                parent_dir = os.path.dirname(self.current_path)
                options.append((".. (Parent Directory)", parent_dir, "", 0))
                self.log(f"Added parent directory: {parent_dir}")

            # Add current entries
            options.extend(current_entries)
            
            # Handle case where selected index is out of bounds
            if self.selected_idx >= len(options):
                self.selected_idx = max(0, len(options) - 1)
            
            # Handle scrolling when selected item would be off-screen
            if self.selected_idx < self.scroll_offset:
                self.scroll_offset = self.selected_idx
            elif self.selected_idx >= self.scroll_offset + self.max_display_items:
                self.scroll_offset = self.selected_idx - self.max_display_items + 1
            
            # Clear screen
            stdscr.clear()
            
            # Display header
            try:
                stdscr.addstr(0, 0, "Disk Usage Analysis Browser", curses.A_BOLD)
                header_line = "=" * (width - 1)
                stdscr.addstr(1, 0, header_line[:width-1])
                
                # Display location and size
                loc_display = f"Location: {self.current_path}"
                if len(loc_display) > width - 1:
                    loc_display = f"Location: ...{self.current_path[-(width-14):]}"
                stdscr.addstr(2, 0, loc_display[:width-1])
                stdscr.addstr(3, 0, f"Size: {current_size}")
                
                # Divider
                stdscr.addstr(4, 0, "-" * (width - 1))

                # Column layout: fixed-width name, then Size, %Dir, %Tot
                col_size = 6
                col_pct = 6  # "XX.X%"
                name_width = 40

                # Column header
                col_header = f"{'Name':<{name_width}}  {'Size':>{col_size}} {'%Dir':>{col_pct}} {'%Tot':>{col_pct}}"
                stdscr.addstr(5, 0, col_header[:width-1], curses.A_DIM)

                # Display directories
                if not options:
                    stdscr.addstr(7, 0, "No subdirectories found")
                else:
                    # Calculate display range
                    display_end = min(self.scroll_offset + self.max_display_items, len(options))

                    for i in range(self.scroll_offset, display_end):
                        # Calculate screen position
                        y_pos = 6 + (i - self.scroll_offset)

                        name, path, size, numeric = options[i]

                        # Show "Rescanning..." overlay for the item being scanned
                        if self.is_scanning() and i == self._scan_target_idx:
                            elapsed = self.scan_elapsed()
                            spinner = "|/-\\"[int(elapsed * 4) % 4]
                            prev = self._scan_durations.get(self._scan_target_path)
                            if prev is not None:
                                remaining = max(0, prev - elapsed)
                                rescan_text = f"{spinner} Rescanning {name}... {elapsed:.0f}s / ~{prev:.0f}s (ETA ~{remaining:.0f}s)"
                            else:
                                rescan_text = f"{spinner} Rescanning {name}... {elapsed:.0f}s"
                            attr = curses.A_BOLD | curses.color_pair(COLOR_SCAN)
                            stdscr.addstr(y_pos, 0, rescan_text[:width-1], attr)
                            continue

                        # Format and draw with per-column coloring
                        if size:
                            pct_folder = (numeric / current_size_bytes * 100) if current_size_bytes > 0 else 0
                            pct_total = (numeric / self.root_size_bytes * 100) if self.root_size_bytes > 0 else 0
                            truncated_name = (name[:name_width-3] + '...') if len(name) > name_width else name
                            name_size_part = f"{truncated_name:<{name_width}}  {size:>{col_size}}"
                            pct_dir_str = f" {pct_folder:>{col_pct - 1}.1f}%"
                            pct_tot_str = f" {pct_total:>{col_pct - 1}.1f}%"

                            selected = i == self.selected_idx
                            base_attr = curses.A_REVERSE if selected else curses.A_NORMAL
                            stdscr.addstr(y_pos, 0, name_size_part[:width-1], base_attr)
                            col_pos = len(name_size_part)
                            if col_pos + len(pct_dir_str) < width - 1:
                                pct_attr = base_attr if selected else (base_attr | self._pct_color(pct_folder))
                                stdscr.addstr(y_pos, col_pos, pct_dir_str, pct_attr)
                                col_pos += len(pct_dir_str)
                            if col_pos + len(pct_tot_str) < width - 1:
                                pct_attr = base_attr if selected else (base_attr | self._pct_color(pct_total))
                                stdscr.addstr(y_pos, col_pos, pct_tot_str, pct_attr)
                        else:
                            base_attr = curses.A_REVERSE if i == self.selected_idx else curses.A_NORMAL
                            stdscr.addstr(y_pos, 0, name[:width-1], base_attr)
                
                # Show scrollbar if needed
                if len(options) > self.max_display_items:
                    scrollbar_height = min(self.max_display_items, 
                                          int(self.max_display_items * self.max_display_items / len(options)))
                    scrollbar_start = int((self.scroll_offset / len(options)) * self.max_display_items)
                    
                    for i in range(self.max_display_items):
                        y_pos = 6 + i
                        if scrollbar_start <= i < scrollbar_start + scrollbar_height:
                            stdscr.addstr(y_pos, width - 2, "█")
                        else:
                            stdscr.addstr(y_pos, width - 2, "│")
                
                # Display footer
                footer_pos = height - 2
                if self.is_scanning():
                    elapsed = self.scan_elapsed()
                    spinner = "|/-\\"[int(elapsed * 4) % 4]
                    target_name = os.path.basename(self._scan_target_path) if self._scan_target_path else "..."
                    prev = self._scan_durations.get(self._scan_target_path)
                    if prev is not None:
                        remaining = max(0, prev - elapsed)
                        scan_footer = f" {spinner} Rescanning {target_name}... {elapsed:.0f}s / ~{prev:.0f}s (ETA ~{remaining:.0f}s) (c: cancel)"
                    else:
                        scan_footer = f" {spinner} Rescanning {target_name}... {elapsed:.0f}s elapsed (c: cancel)"
                    stdscr.addstr(footer_pos, 0, scan_footer[:width-1], curses.A_BOLD | curses.color_pair(COLOR_SCAN))
                else:
                    footer = "↑/↓: Navigate, Enter: Select, s: Rescan, o: Finder, r: Select run, q: Quit"
                    stdscr.addstr(footer_pos, 0, footer[:width-1], curses.A_BOLD)
            except curses.error:
                pass

            stdscr.refresh()

            # Check if a background scan has completed
            if self._scan_result is not None:
                elapsed = self.scan_elapsed()
                self._scan_durations[self._scan_target_path] = elapsed
                if self.apply_scan_result():
                    self.selected_idx = 0
                    self.scroll_offset = 0
                    # Flash a brief confirmation
                    try:
                        footer_pos = height - 2
                        msg = f" Rescan complete ({elapsed:.1f}s)"
                        stdscr.addstr(footer_pos, 0, msg[:width-1], curses.A_BOLD)
                        stdscr.refresh()
                        curses.napms(800)
                    except curses.error:
                        pass
                continue

            # Use non-blocking input during scans so the UI stays responsive
            if self.is_scanning():
                stdscr.nodelay(True)
                key = stdscr.getch()
                if key == -1:
                    curses.napms(100)  # brief sleep to avoid busy loop
                    continue
            else:
                stdscr.nodelay(False)
                key = stdscr.getch()

            if key == ord('q'):
                if self.is_scanning():
                    self._scan_cancel.set()
                break
            elif key == ord('c') and self.is_scanning():
                self._scan_cancel.set()
                self._scan_thread = None
                self._scan_result = None
                self._scan_start = None
                self._scan_target_path = None
                self._scan_target_idx = None
                continue
            elif key == ord('s') and not self.is_scanning():
                if options and 0 <= self.selected_idx < len(options):
                    _, sel_path, _, _ = options[self.selected_idx]
                    if sel_path and os.path.isdir(sel_path):
                        self.start_rescan(sel_path, self.selected_idx)
                continue
            elif key == ord('r'):
                if self.display_timestamp_selector(stdscr):
                    # Reset everything when selecting a new timestamp
                    self.selected_idx = 0
                    self.scroll_offset = 0
                    self.root_path = self.current_path
                    self.root_size_bytes = self.parse_size_to_bytes(self.disk_usage_data[0][0]) if self.disk_usage_data else 0
                else:
                    break
            elif key == ord('o'):
                # Open current directory in Finder
                if os.path.exists(self.current_path):
                    # Temporarily suspend curses
                    curses.endwin()
                    success = self.open_in_finder(self.current_path)
                    # Resume curses
                    stdscr.refresh()
                    if not success:
                        self.show_message(stdscr, "Failed to open directory in Finder.\nPress any key to continue.")
                        stdscr.getch()
            elif key == curses.KEY_UP:
                if self.selected_idx > 0:
                    self.selected_idx -= 1
            elif key == curses.KEY_DOWN:
                if self.selected_idx < len(options) - 1:
                    self.selected_idx += 1
            elif key == curses.KEY_ENTER or key == 10 or key == 13:  # Enter key
                if options and 0 <= self.selected_idx < len(options):
                    # Get the selected option
                    name, path, _, _ = options[self.selected_idx]
                    
                    # Check if it's the parent directory option
                    if name == ".. (Parent Directory)":
                        self.log(f"Going to parent directory: {path}")
                        self.current_path = path
                        
                        # Need to determine which disk_usage.txt file to load
                        # If we're going back to the root, we should load the original file
                        if path == self.root_path:
                            self.log("Going back to root, loading original disk_usage.txt")
                            self.disk_usage_data = self.load_disk_usage_file(self.timestamp_dir)
                        else:
                            # If going back to an intermediate directory, we need to check for a disk_usage.txt file there
                            # Calculate the relative path from the root
                            rel_path = os.path.relpath(path, self.root_path)
                            if rel_path == ".":
                                rel_path = ""
                                
                            subfolder_disk_usage_path = os.path.join(
                                self.output_dir, 
                                self.timestamp_dir, 
                                rel_path, 
                                "disk_usage.txt"
                            )
                            
                            self.log(f"Checking for parent disk_usage.txt at: {subfolder_disk_usage_path}")
                            
                            if os.path.exists(subfolder_disk_usage_path):
                                self.log(f"Found disk_usage.txt for parent folder, loading it")
                                with open(subfolder_disk_usage_path, 'r') as f:
                                    new_data = []
                                    for line in f:
                                        parts = line.strip().split('\t')
                                        if len(parts) == 2:
                                            size, subpath = parts
                                            new_data.append((size, subpath))
                                
                                if new_data:
                                    self.disk_usage_data = new_data
                                    self.log(f"Loaded {len(new_data)} entries from parent disk_usage.txt")
                            else:
                                # If no disk_usage.txt is found, stay with the current data
                                self.log("No parent-specific disk_usage.txt found, staying with current data")
                    else:
                        # Navigate to selected directory
                        self.log(f"Navigating to: {path}")
                        self.current_path = path
                        
                        # Check if the selected directory has its own disk_usage.txt file
                        rel_path = os.path.relpath(path, self.root_path)
                        if rel_path == ".":
                            rel_path = ""
                            
                        self.log(f"Relative path from root: {rel_path}")
                        
                        # Look for a disk_usage.txt file specific to this subfolder
                        subfolder_disk_usage_path = os.path.join(
                            self.output_dir, 
                            self.timestamp_dir, 
                            rel_path, 
                            "disk_usage.txt"
                        )
                        
                        self.log(f"Checking for disk_usage.txt at: {subfolder_disk_usage_path}")
                        
                        if os.path.exists(subfolder_disk_usage_path):
                            self.log(f"Found disk_usage.txt for subfolder, loading it")
                            # Load the disk usage data for this subfolder
                            with open(subfolder_disk_usage_path, 'r') as f:
                                new_data = []
                                for line in f:
                                    parts = line.strip().split('\t')
                                    if len(parts) == 2:
                                        size, subpath = parts
                                        new_data.append((size, subpath))
                            
                            if new_data:
                                self.disk_usage_data = new_data
                                self.log(f"Loaded {len(new_data)} entries from subfolder disk_usage.txt")
                        else:
                            self.log("No subfolder-specific disk_usage.txt found, staying with current data")
                    
                    # Reset selection for new directory
                    self.selected_idx = 0
                    self.scroll_offset = 0
            elif key == curses.KEY_RESIZE:
                # Terminal was resized, just refresh
                continue

def main():
    parser = argparse.ArgumentParser(description='Browse disk usage analysis results.')
    parser.add_argument('--output', '-o', default='./output',
                        help='Base output directory (default: ./output)')
    
    args = parser.parse_args()
    
    # Initialize browser
    browser = OutputBrowser(args.output)
    
    # Setup and run curses application
    try:
        curses.wrapper(browser.browser)
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully
        pass
    
    print("Thank you for using the Disk Usage Analysis Browser!")

if __name__ == "__main__":
    main() 