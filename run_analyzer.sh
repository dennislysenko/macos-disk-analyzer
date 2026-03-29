#!/bin/bash

# Legacy wrapper — prefer using `disk-analyzer` or `python3 disk_analyzer_cli.py` instead.
# This script runs the analyzer directly (without the TUI menu).

echo "Note: consider using 'python3 disk_analyzer_cli.py' for the full TUI experience."
echo ""

python3 "$(dirname "$0")/disk_analyzer.py" "$@"
