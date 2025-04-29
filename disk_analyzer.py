#!/usr/bin/env python3

import os
import subprocess
import argparse
from pathlib import Path
import re
import datetime

def parse_size(size_str):
    """Convert size string with units to bytes."""
    units = {'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4}
    size_str = size_str.upper()
    
    if size_str[-1] in units:
        return float(size_str[:-1]) * units[size_str[-1]]
    return float(size_str)

def format_path_for_output(base_path, target_path):
    """Format path to create corresponding structure in output directory."""
    rel_path = os.path.relpath(target_path, base_path)
    return rel_path if rel_path != '.' else os.path.basename(base_path)

def run_du_command(directory, use_sudo=False, quiet=False):
    """Run the du command on the specified directory and sort results."""
    # First run du command
    du_cmd = ["sudo", "du", "-h", "-d", "1", directory] if use_sudo else ["du", "-h", "-d", "1", directory]
    
    try:
        # Run the du command
        if quiet:
            # Redirect stderr to /dev/null if quiet mode is enabled
            with open(os.devnull, 'w') as devnull:
                du_result = subprocess.run(
                    du_cmd,
                    stdout=subprocess.PIPE,
                    stderr=devnull,
                    text=True,
                    check=False
                )
        else:
            du_result = subprocess.run(
                du_cmd, 
                capture_output=True, 
                text=True,
                check=False
            )
        
        if du_result.returncode != 0 and not quiet:
            print(f"Warning: du command on {directory} exited with code {du_result.returncode}")
            # Print the error output if any
            if du_result.stderr:
                print(f"Error details: {du_result.stderr}")
            
        # Now sort the output (pipe through sort -hr as in original command)
        sort_cmd = ["sort", "-hr"]
        sort_process = subprocess.run(
            sort_cmd,
            input=du_result.stdout,
            capture_output=True,
            text=True
        )
        
        return sort_process.stdout
    except subprocess.SubprocessError as e:
        if not quiet:
            print(f"Error running command on {directory}: {e}")
        return ""

def create_output_dir(output_base, path_component):
    """Create output directory maintaining structure."""
    output_dir = os.path.join(output_base, path_component)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

def save_results(output_path, content):
    """Save the du command results to a file."""
    with open(output_path, "w") as f:
        f.write(content)

def analyze_directory(directory, output_base, base_directory, min_size_gb=2, use_sudo=False, quiet=False):
    """
    Analyze a directory with du command and recursively process large subdirectories.
    
    Args:
        directory: Directory to analyze
        output_base: Base output directory
        base_directory: Original base directory for creating relative paths
        min_size_gb: Minimum size in GB to process subdirectories
        use_sudo: Whether to use sudo for du commands
        quiet: Whether to suppress error messages
    """
    print(f"Analyzing: {directory}")
    
    # Run du command on current directory
    du_output = run_du_command(directory, use_sudo, quiet)
    if not du_output:
        return
    
    # Create output structure
    path_component = format_path_for_output(base_directory, directory)
    
    # Create proper output directory path
    if os.path.normpath(directory) == os.path.normpath(base_directory):
        # For the base directory itself, use the output base directly
        output_dir = output_base
        output_filename = "disk_usage.txt"
    else:
        # For subdirectories, maintain the directory structure
        output_dir = os.path.join(output_base, path_component)
        # Create the directory
        os.makedirs(output_dir, exist_ok=True)
        output_filename = "disk_usage.txt"
    
    # Save results
    output_path = os.path.join(output_dir, output_filename)
    save_results(output_path, du_output)
    
    print(f"Saved results to: {output_path}")
    
    # Find subdirectories larger than threshold
    min_size_bytes = min_size_gb * 1024**3
    large_subdirs = []
    
    for line in du_output.strip().split('\n'):
        parts = line.strip().split('\t')
        if len(parts) != 2:
            continue
            
        size_str, path = parts
        
        # Skip the directory itself (precise path comparison)
        if os.path.normpath(path) == os.path.normpath(directory):
            continue
            
        # Convert size to bytes (handle units like K, M, G, T)
        try:
            # Extract numeric size and unit from du output (e.g., "2.5G")
            match = re.match(r'([0-9.]+)([KMGT]?)', size_str)
            if match:
                size_value, unit = match.groups()
                size_str = f"{size_value}{unit}"
                size_bytes = parse_size(size_str)
                
                # If directory exceeds threshold and is actually a directory, process it
                if size_bytes >= min_size_bytes and os.path.isdir(path):
                    large_subdirs.append(path)
                    print(f"Found large subdirectory: {path} ({size_str})")
        except (ValueError, TypeError) as e:
            if not quiet:
                print(f"Error parsing size for {path}: {e}")
    
    # Process large subdirectories recursively
    for subdir in large_subdirs:
        analyze_directory(subdir, output_base, base_directory, min_size_gb, use_sudo, quiet)

def main():
    parser = argparse.ArgumentParser(description='Analyze disk usage recursively.')
    parser.add_argument('directory', nargs='?', default=os.path.expanduser('~'),
                        help='Base directory to analyze (default: user home)')
    parser.add_argument('--output', '-o', default='./output',
                        help='Base output directory (default: ./output)')
    parser.add_argument('--min-size', '-m', type=float, default=2.0,
                        help='Minimum size in GB to process subdirectories (default: 2.0)')
    parser.add_argument('--sudo', '-s', action='store_true',
                        help='Use sudo for du commands (access more directories)')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='Suppress error messages from du command')
    parser.add_argument('--debug', '-d', action='store_true',
                        help='Enable debug output')
    
    args = parser.parse_args()
    
    # Generate timestamp for this run
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    
    # Convert to absolute paths
    directory = os.path.abspath(args.directory)
    # Create a timestamped output directory
    base_output = os.path.abspath(args.output)
    output_base = os.path.join(base_output, timestamp)
    
    # Create output directory
    os.makedirs(output_base, exist_ok=True)
    
    # Display permission information
    print("\nDisk Analyzer Permission Information:")
    print("------------------------------------")
    print("This script will try to analyze disk usage in various directories.")
    print("You may see system permission requests for folders or applications.")
    print("For the most complete analysis, please grant these permissions when prompted.")
    if args.sudo:
        print("You've enabled sudo mode, which may prompt for your password.")
    print("------------------------------------\n")
    
    # Start analysis
    analyze_directory(directory, output_base, directory, args.min_size, args.sudo, args.quiet)
    
    print(f"Analysis complete. Results saved to {output_base}")

if __name__ == "__main__":
    main() 