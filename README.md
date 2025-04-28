# Disk Analyzer

A Python script that analyzes disk usage recursively on directories exceeding a specified size threshold.

## Features

- Runs `du -h -d 1` on specified directories and sorts results by size
- Recursively analyzes subdirectories exceeding a minimum size (default: 2GB)
- Saves output to a directory structure that mirrors the filesystem
- Each output file is named after its corresponding directory with "_disk_usage.txt" suffix
- Optional sudo mode for accessing restricted directories
- Configurable error handling with quiet mode

## Requirements

- Python 3.6 or later

## Usage

```bash
# Basic usage (analyzes your home directory by default)
python3 disk_analyzer.py

# Analyze a specific directory
python3 disk_analyzer.py /path/to/directory

# Specify output directory and minimum subdirectory size (in GB)
python3 disk_analyzer.py /path/to/directory --output /path/to/output --min-size 1.5

# Use sudo to access restricted directories
python3 disk_analyzer.py --sudo

# Suppress error messages
python3 disk_analyzer.py --quiet
```

## Options

- `directory`: Directory to analyze (default: user's home directory)
- `--output`, `-o`: Output directory to save results (default: ./output)
- `--min-size`, `-m`: Minimum size in GB to process subdirectories (default: 2.0)
- `--sudo`, `-s`: Use sudo for du commands (gives access to more directories)
- `--quiet`, `-q`: Suppress error messages from du command (similar to 2>/dev/null)

## Using the Shell Wrapper

For convenience, a shell wrapper script is provided:

```bash
# Show help and available options
./run_analyzer.sh --help

# Run with default options
./run_analyzer.sh

# Run with custom options
./run_analyzer.sh --dir /path/to/directory --output ./results --min-size 1.0 --sudo --quiet
```

## Example

```bash
# Analyze the /Users/username directory, saving results to ./disk_analysis
# and recursively check subdirectories larger than 1GB with sudo access
python3 disk_analyzer.py /Users/username --output ./disk_analysis --min-size 1 --sudo
```

## Output

The script creates text files in the output directory, maintaining the relative path structure of analyzed directories. Each file contains the sorted output of `du -h -d 1` for the corresponding directory.

## Error Handling

By default, the script will display error messages from the `du` command. These errors typically occur when the tool can't access certain directories due to permission restrictions.

If you prefer to hide these error messages (similar to using `2>/dev/null` in the original command), use the `--quiet` option. 