#!/bin/bash

# A simple wrapper for the disk_analyzer.py script

# Make the script executable if it's not already
if [ ! -x ./disk_analyzer.py ]; then
    echo "Making disk_analyzer.py executable..."
    chmod +x ./disk_analyzer.py
fi

# Default values
TARGET_DIR="$HOME"
OUTPUT_DIR="./output"
MIN_SIZE="2.0"
USE_SUDO=false
QUIET_MODE=false

# Help function
show_help() {
    echo "Usage: ./run_analyzer.sh [options]"
    echo ""
    echo "Options:"
    echo "  -d, --dir DIR       Target directory to analyze (default: $HOME)"
    echo "  -o, --output DIR    Output directory (default: ./output)"
    echo "  -m, --min-size GB   Minimum size in GB to process subdirectories (default: 2.0)"
    echo "  -s, --sudo          Use sudo for du commands (access more directories)"
    echo "  -q, --quiet         Suppress error messages from du command"
    echo "  -h, --help          Show this help message"
    echo ""
    echo "Example:"
    echo "  ./run_analyzer.sh --dir /Users/username --output ./disk_report --min-size 1.5 --sudo"
    exit 0
}

# Parse command line arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -d|--dir) TARGET_DIR="$2"; shift ;;
        -o|--output) OUTPUT_DIR="$2"; shift ;;
        -m|--min-size) MIN_SIZE="$2"; shift ;;
        -s|--sudo) USE_SUDO=true ;;
        -q|--quiet) QUIET_MODE=true ;;
        -h|--help) show_help ;;
        *) echo "Unknown parameter: $1"; show_help ;;
    esac
    shift
done

echo "Disk Analyzer"
echo "============="
echo "Target Directory: $TARGET_DIR"
echo "Output Directory: $OUTPUT_DIR"
echo "Min Size for Recursion: ${MIN_SIZE}GB"
if [ "$USE_SUDO" = true ]; then
    echo "Using sudo: Yes (will prompt for password if needed)"
else
    echo "Using sudo: No"
fi
if [ "$QUIET_MODE" = true ]; then
    echo "Error display: Suppressed"
else
    echo "Error display: Showing all errors"
fi
echo ""
echo "Press Enter to continue or Ctrl+C to cancel..."
read

# Prepare command
CMD="python3 ./disk_analyzer.py \"$TARGET_DIR\" --output \"$OUTPUT_DIR\" --min-size \"$MIN_SIZE\""
if [ "$USE_SUDO" = true ]; then
    CMD="$CMD --sudo"
fi
if [ "$QUIET_MODE" = true ]; then
    CMD="$CMD --quiet"
fi

# Run the Python script
eval $CMD

echo ""
echo "Analysis complete. Check $OUTPUT_DIR for results." 