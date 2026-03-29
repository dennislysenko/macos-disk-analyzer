# Disk Analyzer

A fast, terminal-based disk usage analyzer for macOS. Scans directories recursively, saves results, and lets you browse them in an interactive TUI.

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
# Interactive TUI — scan and browse from one interface
disk-analyzer
```

### Subcommands (power users)

```bash
# Run a scan
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
| `--min-size`, `-m` | Min size in GB to recurse | `2.0` |
| `--sudo`, `-s` | Use sudo for `du` commands | off |
| `--quiet`, `-q` | Suppress `du` error messages | off |
| `--workers`, `-w` | Parallel workers | `8` |
| `--timeout`, `-t` | Timeout per directory (seconds) | `300` |

### Browser Controls

| Key | Action |
|-----|--------|
| ↑/↓ | Navigate |
| Enter | Select directory |
| o | Open in Finder |
| r | Return to run selection |
| q | Quit |

## Configuration

Config file: `~/.config/disk-analyzer/config.toml`

```toml
# default_directory = "~"
# min_size_gb = 2.0
# output_dir = "./output"
# workers = 4
# timeout = 300

# API key for AI-powered explanations (beta, coming soon)
# Also accepted via DISK_ANALYZER_API_KEY env var
# api_key = ""
```

## How It Works

1. Runs `du -h -d 1` on the target directory
2. Recursively analyzes subdirectories exceeding the minimum size threshold
3. Saves results to timestamped directories mirroring the filesystem structure
4. The TUI browser lets you navigate results sorted by size, with color-coded percentage columns

## GUI Browser

A graphical browser with pie charts is also available (requires `matplotlib`):

```bash
disk-analyzer browse --gui
pip install matplotlib  # if not installed
```
