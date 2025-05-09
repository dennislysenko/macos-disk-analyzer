#!/usr/bin/env python3

import os
import datetime
import curses
import argparse
import subprocess

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
        # Set up log file path in the output directory
        self.log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_debug.log")
        
    def log(self, message):
        """Write a debug message to the log file with timestamp"""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        with open(self.log_file, "a") as f:
            f.write(f"[{timestamp}] {message}\n")
        
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
        
        # Remove the numeric size from the final entries
        return size, [(name, path, size) for name, path, size, _ in entries]
            
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
            # Use subprocess to run the 'open' command which opens Finder on macOS
            subprocess.run(['open', path])
            return True
        except Exception as e:
            self.log(f"Error opening Finder: {str(e)}")
            return False
    
    def browser(self, stdscr):
        """Main curses-based browser"""
        # Setup curses
        curses.curs_set(0)  # Hide cursor
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
            self.max_display_items = height - 8
            
            # Get current directory information
            current_size, current_entries = self.get_current_directory_info()
            
            # Build options list with parent directory if not at root level
            options = []
            
            # Keep track of the initial root directory (from first timestamp selection)
            # This is used to detect if we're at the top level
            if not hasattr(self, 'root_path') and len(self.disk_usage_data) > 0:
                self.root_path = self.disk_usage_data[0][1]
                self.log(f"Setting root path to: {self.root_path}")
            
            # Add parent directory entry if not at the root level
            if self.current_path != getattr(self, 'root_path', None):
                parent_dir = os.path.dirname(self.current_path)
                options.append((".. (Parent Directory)", parent_dir, ""))
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
                
                # Display directories
                if not options:
                    stdscr.addstr(6, 0, "No subdirectories found")
                else:
                    # Calculate display range
                    display_end = min(self.scroll_offset + self.max_display_items, len(options))
                    
                    for i in range(self.scroll_offset, display_end):
                        # Calculate screen position
                        y_pos = 5 + (i - self.scroll_offset)
                        
                        name, path, size = options[i]
                        
                        # Format display string
                        if size:
                            display_text = f"{name} - {size}"
                        else:
                            display_text = name
                            
                        # Truncate if too long
                        if len(display_text) > width - 2:
                            display_text = display_text[:width-5] + "..."
                        
                        # Highlight selected item
                        if i == self.selected_idx:
                            stdscr.addstr(y_pos, 0, display_text, curses.A_REVERSE)
                        else:
                            stdscr.addstr(y_pos, 0, display_text)
                
                # Show scrollbar if needed
                if len(options) > self.max_display_items:
                    scrollbar_height = min(self.max_display_items, 
                                          int(self.max_display_items * self.max_display_items / len(options)))
                    scrollbar_start = int((self.scroll_offset / len(options)) * self.max_display_items)
                    
                    for i in range(self.max_display_items):
                        y_pos = 5 + i
                        if scrollbar_start <= i < scrollbar_start + scrollbar_height:
                            stdscr.addstr(y_pos, width - 2, "█")
                        else:
                            stdscr.addstr(y_pos, width - 2, "│")
                
                # Display footer
                footer_pos = height - 2
                footer = "↑/↓: Move selection, Enter: Select, o: Open in Finder, r: Select run, q: Quit"
                stdscr.addstr(footer_pos, 0, footer[:width-1], curses.A_BOLD)
            except curses.error:
                # Catch curses errors (may happen during resizing)
                pass
            
            stdscr.refresh()
            
            # Handle key input
            key = stdscr.getch()
            
            if key == ord('q'):
                break
            elif key == ord('r'):
                if self.display_timestamp_selector(stdscr):
                    # Reset everything when selecting a new timestamp
                    self.selected_idx = 0
                    self.scroll_offset = 0
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
                    name, path, _ = options[self.selected_idx]
                    
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