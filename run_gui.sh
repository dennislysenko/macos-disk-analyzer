#!/bin/bash
# Run the GUI browser with the virtual environment

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Activate virtual environment and run the GUI
source "$SCRIPT_DIR/venv/bin/activate"
python "$SCRIPT_DIR/browser.py" --gui "$@"
