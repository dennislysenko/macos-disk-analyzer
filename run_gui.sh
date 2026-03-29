#!/bin/bash

# Legacy wrapper — prefer using `disk-analyzer` or `python3 disk_analyzer_cli.py browse --gui` instead.
# This script launches the GUI browser (requires matplotlib).

echo "Note: consider using 'python3 disk_analyzer_cli.py browse --gui' instead."
echo ""

python3 "$(dirname "$0")/disk_analyzer_cli.py" browse --gui "$@"
