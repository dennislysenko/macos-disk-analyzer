#!/usr/bin/env python3

import os
import datetime
import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

class DiskAnalyzerGUI:
    def __init__(self, output_dir="./output"):
        self.output_dir = os.path.abspath(output_dir)
        self.current_timestamp = None
        self.current_path = None
        self.timestamp_dir = None
        self.disk_usage_data = []
        self.root_path = None
        self.root_size_bytes = 0

        # Create main window
        self.root = tk.Tk()
        self.root.title("Disk Usage Analysis Browser")
        self.root.geometry("1200x700")

        # Setup UI
        self.setup_ui()

    def setup_ui(self):
        """Setup the main UI layout"""
        # Create main container with two panels
        main_container = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_container.pack(fill=tk.BOTH, expand=True)

        # Left panel for directory listing
        left_panel = ttk.Frame(main_container)
        main_container.add(left_panel, weight=2)

        # Right panel for pie chart
        right_panel = ttk.Frame(main_container)
        main_container.add(right_panel, weight=1)

        # Setup left panel
        self.setup_left_panel(left_panel)

        # Setup right panel
        self.setup_right_panel(right_panel)

        # Setup menu bar
        self.setup_menu()

    def setup_left_panel(self, parent):
        """Setup the left panel with directory listing"""
        # Header frame
        header_frame = ttk.Frame(parent)
        header_frame.pack(fill=tk.X, padx=10, pady=5)

        # Location label
        ttk.Label(header_frame, text="Location:", font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W)
        self.location_label = ttk.Label(header_frame, text="", wraplength=500)
        self.location_label.pack(anchor=tk.W, fill=tk.X)

        # Size label
        self.size_label = ttk.Label(header_frame, text="Size: ", font=("TkDefaultFont", 10))
        self.size_label.pack(anchor=tk.W, pady=(5, 0))

        # Selected items label
        self.selected_label = ttk.Label(header_frame, text="", font=("TkDefaultFont", 10, "bold"), foreground="#4a9eff")
        self.selected_label.pack(anchor=tk.W, pady=(5, 0))

        # Separator
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=5)

        # Listbox frame with scrollbar
        list_frame = ttk.Frame(parent)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Scrollbar
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Listbox
        self.directory_listbox = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            font=("Monaco", 11),
            selectmode=tk.EXTENDED,
            activestyle="none"
        )
        self.directory_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.directory_listbox.yview)

        # Bind events
        self.directory_listbox.bind('<Double-Button-1>', self.on_directory_select)
        self.directory_listbox.bind('<Return>', self.on_directory_select)
        self.directory_listbox.bind('<<ListboxSelect>>', self.on_selection_change)

        # Button frame
        button_frame = ttk.Frame(parent)
        button_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Button(button_frame, text="Open in Finder", command=self.open_in_finder).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Select Run", command=self.show_timestamp_selector).pack(side=tk.LEFT, padx=5)

    def setup_right_panel(self, parent):
        """Setup the right panel with pie chart"""
        # Title
        self.chart_title = ttk.Label(parent, text="Current Level Distribution",
                  font=("TkDefaultFont", 12, "bold"))
        self.chart_title.pack(pady=10)

        # Create matplotlib figure
        self.fig = Figure(figsize=(5, 5), dpi=100)
        self.ax = self.fig.add_subplot(111)

        # Create canvas
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Initial empty chart
        self.update_pie_chart([])

    def setup_menu(self):
        """Setup menu bar"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Select Run", command=self.show_timestamp_selector)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)

        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Open in Finder", command=self.open_in_finder)

    def parse_size_to_bytes(self, size_str):
        """Convert size string with units (like '2.5G') to bytes"""
        if not size_str:
            return 0

        size_str = size_str.strip().upper()
        multiplier = {'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4, 'B': 1}

        try:
            # Extract numeric value and unit
            if size_str[-1] in multiplier:
                numeric_value = float(size_str[:-1])
                return numeric_value * multiplier[size_str[-1]]
            else:
                # No unit, assume bytes
                return float(size_str)
        except (ValueError, IndexError):
            return 0

    def format_size(self, size_bytes):
        """Convert bytes to human-readable format"""
        if size_bytes == 0:
            return "0B"

        units = ['B', 'K', 'M', 'G', 'T']
        unit_index = 0

        size = float(size_bytes)
        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1

        # Format with appropriate precision
        if size >= 100:
            return f"{size:.0f}{units[unit_index]}"
        elif size >= 10:
            return f"{size:.1f}{units[unit_index]}"
        else:
            return f"{size:.2f}{units[unit_index]}"

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

    def show_timestamp_selector(self):
        """Show dialog to select a timestamp"""
        timestamps = self.load_timestamps()

        if not timestamps:
            messagebox.showinfo("No Runs Found", "No analysis runs found in the output directory.")
            return

        # Create selection dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Select Analysis Run")
        dialog.geometry("500x400")
        dialog.transient(self.root)
        dialog.grab_set()

        # Title
        ttk.Label(dialog, text="Available Analysis Runs",
                  font=("TkDefaultFont", 12, "bold")).pack(pady=10)

        # Listbox with scrollbar
        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, font=("TkDefaultFont", 11))
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=listbox.yview)

        # Populate listbox
        for dir_name, timestamp in timestamps:
            formatted_time = self.format_timestamp(timestamp)
            listbox.insert(tk.END, formatted_time)

        # Select first item by default
        if timestamps:
            listbox.selection_set(0)
            listbox.activate(0)

        # Button frame
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=10)

        def on_select():
            selection = listbox.curselection()
            if selection:
                idx = selection[0]
                timestamp_dir, _ = timestamps[idx]
                self.load_timestamp_data(timestamp_dir)
                dialog.destroy()

        def on_cancel():
            dialog.destroy()

        ttk.Button(button_frame, text="Select", command=on_select).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=on_cancel).pack(side=tk.RIGHT)

        # Bind double-click and Enter key
        listbox.bind('<Double-Button-1>', lambda e: on_select())
        listbox.bind('<Return>', lambda e: on_select())

    def load_timestamp_data(self, timestamp_dir):
        """Load disk usage data for a specific timestamp"""
        # Load the disk_usage.txt file
        disk_usage_path = os.path.join(self.output_dir, timestamp_dir, "disk_usage.txt")

        if not os.path.exists(disk_usage_path):
            messagebox.showerror("Error", "Could not load disk usage data.")
            return

        self.disk_usage_data = []
        with open(disk_usage_path, 'r') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) == 2:
                    size, path = parts
                    self.disk_usage_data.append((size, path))

        if not self.disk_usage_data:
            messagebox.showerror("Error", "No data found in disk usage file.")
            return

        # Set the current timestamp directory
        self.timestamp_dir = timestamp_dir

        # Set the current path to the first directory (typically the base directory)
        self.current_path = self.disk_usage_data[0][1]
        self.root_path = self.current_path
        self.root_size_bytes = self.parse_size_to_bytes(self.disk_usage_data[0][0])

        # Update the display
        self.update_display()

    def load_disk_usage_file(self, rel_path):
        """Load a disk_usage.txt file for a specific relative path"""
        if rel_path == "" or rel_path == ".":
            disk_usage_path = os.path.join(self.output_dir, self.timestamp_dir, "disk_usage.txt")
        else:
            disk_usage_path = os.path.join(self.output_dir, self.timestamp_dir, rel_path, "disk_usage.txt")

        if not os.path.exists(disk_usage_path):
            return None

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

        # Return with numeric sizes for pie chart
        return size, [(name, path, size, numeric) for name, path, size, numeric in entries]

    def update_display(self):
        """Update the directory listing and pie chart"""
        if not self.current_path:
            return

        # Update location label
        self.location_label.config(text=self.current_path)

        # Get current directory info
        current_size, entries = self.get_current_directory_info()

        # Update size label
        self.size_label.config(text=f"Size: {current_size}")

        # Clear selection label
        self.selected_label.config(text="")

        # Reset chart title
        self.chart_title.config(text="Current Level Distribution")

        # Clear listbox
        self.directory_listbox.delete(0, tk.END)

        # Store entries for navigation
        self.current_entries = []

        # Add parent directory if not at root
        if self.current_path != self.root_path:
            parent_dir = os.path.dirname(self.current_path)
            self.directory_listbox.insert(tk.END, ".. (Parent Directory)")
            self.current_entries.append((".. (Parent Directory)", parent_dir, "", 0))

        # Compute current folder size for percentage
        current_size_bytes = self.parse_size_to_bytes(current_size)

        # Add entries with percentage columns
        for name, path, size, numeric in entries:
            pct_folder = (numeric / current_size_bytes * 100) if current_size_bytes > 0 else 0
            pct_total = (numeric / self.root_size_bytes * 100) if self.root_size_bytes > 0 else 0
            display_text = f"{name}  {size:>6}  {pct_folder:5.1f}% dir  {pct_total:5.1f}% tot"
            self.directory_listbox.insert(tk.END, display_text)
            self.current_entries.append((name, path, size, numeric))

        # Update pie chart with current entries (excluding parent)
        chart_entries = [(name, numeric) for name, path, size, numeric in entries]
        self.update_pie_chart(chart_entries)

    def update_pie_chart(self, entries):
        """Update the pie chart with current directory distribution"""
        self.ax.clear()

        if not entries or len(entries) == 0:
            self.ax.text(0.5, 0.5, 'No data', ha='center', va='center', fontsize=14)
            self.ax.axis('off')
        else:
            # Limit to top 10 entries for readability
            top_entries = entries[:10]

            # Calculate "Others" if there are more than 10
            if len(entries) > 10:
                others_size = sum(size for _, size in entries[10:])
                top_entries.append(("Others", others_size))

            names = [name for name, _ in top_entries]
            sizes = [size for _, size in top_entries]

            # Create color palette
            colors = plt.cm.Set3(range(len(names)))

            # Create pie chart
            wedges, texts, autotexts = self.ax.pie(
                sizes,
                labels=None,  # Don't show labels on the pie
                autopct='%1.1f%%',
                startangle=90,
                colors=colors,
                textprops={'fontsize': 8}
            )

            # Add legend
            self.ax.legend(
                wedges,
                [name[:20] + "..." if len(name) > 20 else name for name in names],
                loc="center left",
                bbox_to_anchor=(1, 0, 0.5, 1),
                fontsize=8
            )

        self.fig.tight_layout()
        self.canvas.draw()

    def on_directory_select(self, event=None):
        """Handle directory selection"""
        selection = self.directory_listbox.curselection()
        if not selection:
            return

        idx = selection[0]
        if idx >= len(self.current_entries):
            return

        name, path, _, _ = self.current_entries[idx]

        # Check if it's the parent directory
        if name == ".. (Parent Directory)":
            self.navigate_to_parent()
        else:
            self.navigate_to_directory(path)

    def on_selection_change(self, event=None):
        """Handle selection change to update selected items display and pie chart"""
        selection = self.directory_listbox.curselection()

        # Show all entries in pie chart by default
        if hasattr(self, 'current_entries'):
            all_chart_entries = [(name, numeric) for name, path, size, numeric in self.current_entries
                           if name != ".. (Parent Directory)"]
        else:
            all_chart_entries = []

        if not selection or len(selection) == 0:
            # No selection - show all items
            self.selected_label.config(text="")
            self.chart_title.config(text="Current Level Distribution")
            self.update_pie_chart(all_chart_entries)
            return

        # Calculate total size of selected items
        selected_entries = []
        total_selected_size = 0

        for idx in selection:
            if idx < len(self.current_entries):
                name, path, size, numeric = self.current_entries[idx]
                # Skip parent directory in calculations
                if name != ".. (Parent Directory)":
                    selected_entries.append((name, numeric))
                    total_selected_size += numeric

        if not selected_entries:
            # Only parent directory selected
            self.selected_label.config(text="")
            self.chart_title.config(text="Current Level Distribution")
            self.update_pie_chart(all_chart_entries)
            return

        # Get current directory size for percentage calculation
        current_size_str = self.size_label.cget("text").replace("Size: ", "")
        current_size_bytes = self.parse_size_to_bytes(current_size_str)

        # Calculate percentage
        if current_size_bytes > 0:
            percentage = (total_selected_size / current_size_bytes) * 100
        else:
            percentage = 0

        # Format the selected size
        formatted_size = self.format_size(total_selected_size)

        # Only show multi-select view if 2 or more items are selected
        if len(selected_entries) >= 2:
            # Update label
            count_text = f"{len(selected_entries)} items"
            self.selected_label.config(text=f"Selected: {count_text} - {formatted_size} ({percentage:.1f}%)")

            # Update chart title and show only selected items
            self.chart_title.config(text="Selected Items Breakdown")
            self.update_pie_chart(selected_entries)
        else:
            # Single selection - show info but keep full chart
            self.selected_label.config(text=f"Selected: 1 item - {formatted_size} ({percentage:.1f}%)")
            self.chart_title.config(text="Current Level Distribution")
            self.update_pie_chart(all_chart_entries)

    def navigate_to_parent(self):
        """Navigate to parent directory"""
        parent_dir = os.path.dirname(self.current_path)

        # Try to load parent-specific disk_usage.txt
        if parent_dir == self.root_path:
            # Going back to root
            self.disk_usage_data = self.load_disk_usage_file("")
        else:
            # Try to load parent's disk_usage.txt
            rel_path = os.path.relpath(parent_dir, self.root_path)
            parent_data = self.load_disk_usage_file(rel_path)
            if parent_data:
                self.disk_usage_data = parent_data

        self.current_path = parent_dir
        self.update_display()

    def navigate_to_directory(self, path):
        """Navigate to a specific directory"""
        # Check if the selected directory has its own disk_usage.txt file
        rel_path = os.path.relpath(path, self.root_path)

        subfolder_data = self.load_disk_usage_file(rel_path)
        if subfolder_data:
            self.disk_usage_data = subfolder_data

        self.current_path = path
        self.update_display()

    def open_in_finder(self):
        """Open the current directory in Finder"""
        if not self.current_path or not os.path.exists(self.current_path):
            messagebox.showerror("Error", "Current directory does not exist.")
            return

        try:
            subprocess.run(['open', self.current_path])
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open Finder: {str(e)}")

    def run(self):
        """Run the GUI application"""
        # Show timestamp selector on startup
        self.root.after(100, self.show_timestamp_selector)

        # Start main loop
        self.root.mainloop()

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Browse disk usage analysis results (GUI).')
    parser.add_argument('--output', '-o', default='./output',
                        help='Base output directory (default: ./output)')

    args = parser.parse_args()

    # Create and run GUI
    app = DiskAnalyzerGUI(args.output)
    app.run()

if __name__ == "__main__":
    main()
