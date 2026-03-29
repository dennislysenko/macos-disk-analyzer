# Disk Analyzer

A fast, terminal-based disk usage analyzer for macOS. Scans directories in parallel, saves results, and lets you browse them in an interactive TUI — all from one command.

Created because OmniDiskSweeper was killing me with freezes and pauses.

## Demo

> **Note:** This demo is outdated and needs to be re-recorded to show the new unified TUI.

![Browser Demo](browser.gif)

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/dennislysenko/macos-disk-analyzer/main/install.sh | sh
```

This installs the `disk-analyzer` command to `~/.local/bin`. No sudo required. Only needs Python 3.6+ (pre-installed on macOS).

<details>
<summary>Manual install (clone)</summary>

```bash
git clone https://github.com/dennislysenko/macos-disk-analyzer.git
cd macos-disk-analyzer
python3 disk_analyzer_cli.py
```
</details>

## Usage

```bash
# Launch the interactive TUI
disk-analyzer
```

The TUI main menu gives you three options:
- **Scan** — choose a target (home folder, entire drive, or custom path), pick a min-size threshold, and watch progress in a fullscreen view with per-worker status
- **Browse** — explore previous scan results sorted by size with color-coded percentages
- **Quit**

### Scan UI

The scan screen walks you through setup:
1. **Target selection** — toggle between home folder (`~`), entire drive (`/`), or enter a custom path
2. **Min size** — choose how deep to recurse (smaller = more detail but slower)

During the scan you get:
- Progress bar with ETA (improves after first scan using heuristics from prior runs)
- Per-worker status showing what each of the 8 parallel workers is scanning
- Press **Tab** to toggle between worker view and chronological log
- Press **c** to cancel (with confirmation)

After the scan completes, press **Enter** to jump straight into the browser.

### Subcommands (power users)

```bash
# Run a scan directly
disk-analyzer scan ~
disk-analyzer scan /path/to/dir --min-size 1 --sudo --quiet

# Browse previous results
disk-analyzer browse
disk-analyzer browse --output /path/to/output
```

### Scan Options

| Flag | Description | Default |
|------|-------------|---------|
| `directory` | Directory to analyze | `~` |
| `--output`, `-o` | Output directory for results | `./output` |
| `--min-size`, `-m` | Min size in GB to recurse into subdirectories | `2.0` |
| `--sudo`, `-s` | Use sudo for `du` commands | off |
| `--quiet`, `-q` | Suppress `du` error messages | on |
| `--workers`, `-w` | Parallel workers | `8` |
| `--timeout`, `-t` | Slow-scan warning threshold in seconds | `120` |

### Browser Controls

| Key | Action |
|-----|--------|
| ↑/↓ | Navigate |
| Enter | Select directory |
| o | Open in Finder |
| r | Return to run selection |
| q | Quit / back to menu |

## Configuration

Config file: `~/.config/disk-analyzer/config.toml` (created by the installer)

```toml
# default_directory = "~"
# min_size_gb = 2.0
# output_dir = "./output"
# workers = 8
# timeout = 120

# API key for AI-powered explanations (beta, coming soon)
# Also accepted via DISK_ANALYZER_API_KEY env var
# api_key = ""
```

## How It Works

1. Lists top-level subdirectories instantly and fans out `du -h -d 1` across 8 parallel workers
2. Uses lookahead scheduling — children are pre-enqueued via `listdir` before the parent's `du` finishes, keeping all workers busy
3. Recursively analyzes subdirectories exceeding the min-size threshold (default 2GB), up to 10 levels deep
4. Saves results to timestamped directories mirroring the filesystem structure
5. Synthesizes parent `disk_usage.txt` files from child results for seamless browsing
6. The TUI browser lets you navigate results sorted by size, with color-coded percentage columns (%dir, %tot)

## GUI Browser

A graphical browser with pie charts is also available (requires `matplotlib`):

```bash
disk-analyzer browse --gui
pip install matplotlib  # if not installed
```
