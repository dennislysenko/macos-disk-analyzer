#!/usr/bin/env python3

import argparse
import sys

def main():
    parser = argparse.ArgumentParser(description='Browse disk usage analysis results.')
    parser.add_argument('--output', '-o', default='./output',
                        help='Base output directory (default: ./output)')
    parser.add_argument('--gui', '-g', action='store_true',
                        help='Launch GUI browser (default: TUI/terminal browser)')

    args = parser.parse_args()

    if args.gui:
        # Launch GUI browser
        try:
            from browser_gui import DiskAnalyzerGUI
            app = DiskAnalyzerGUI(args.output)
            app.run()
        except ImportError as e:
            print(f"Error: Could not launch GUI browser.", file=sys.stderr)
            print(f"Make sure you have the required dependencies installed:", file=sys.stderr)
            print(f"  pip install matplotlib", file=sys.stderr)
            print(f"  brew install python-tk@3.14  # for tkinter", file=sys.stderr)
            print(f"\nOr run: ./run_gui.sh", file=sys.stderr)
            sys.exit(1)
    else:
        # Launch TUI browser
        import curses
        from browser_tui import OutputBrowser

        browser = OutputBrowser(args.output)

        try:
            curses.wrapper(browser.browser)
        except KeyboardInterrupt:
            pass

        print("Thank you for using the Disk Usage Analysis Browser!")

if __name__ == "__main__":
    main()
