#!/bin/sh
set -e

# Disk Analyzer Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/dennislysenko/macos-disk-analyzer/main/install.sh | sh

REPO="dennislysenko/macos-disk-analyzer"
BRANCH="main"
BASE_URL="https://raw.githubusercontent.com/${REPO}/${BRANCH}"

INSTALL_DIR="${HOME}/.local/bin"
LIB_DIR="${HOME}/.local/share/disk-analyzer"
CONFIG_DIR="${HOME}/.config/disk-analyzer"

FILES="disk_analyzer_cli.py disk_analyzer.py browser_tui.py browser.py browser_gui.py"

echo "Disk Analyzer Installer"
echo "======================="
echo ""

# Check for python3
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required but not found."
    echo "Install Python 3.6+ from https://www.python.org or via: brew install python3"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Found python3 ${PYTHON_VERSION}"

# Check for curses (required for TUI)
if ! python3 -c "import curses" 2>/dev/null; then
    echo "Error: Python curses module not found."
    echo "This is usually included with Python on macOS. Try reinstalling Python."
    exit 1
fi

# Create directories
mkdir -p "${INSTALL_DIR}"
mkdir -p "${LIB_DIR}"
mkdir -p "${CONFIG_DIR}"

echo "Installing to ${LIB_DIR}..."

# Download Python files
for file in ${FILES}; do
    echo "  Downloading ${file}..."
    curl -fsSL "${BASE_URL}/${file}" -o "${LIB_DIR}/${file}"
done

# Create config file if it doesn't exist
if [ ! -f "${CONFIG_DIR}/config.toml" ]; then
    echo "  Creating default config..."
    curl -fsSL "${BASE_URL}/config.example.toml" -o "${CONFIG_DIR}/config.toml"
fi

# Create wrapper script
echo "  Creating disk-analyzer command..."
cat > "${INSTALL_DIR}/disk-analyzer" << 'WRAPPER'
#!/bin/sh
exec python3 "${HOME}/.local/share/disk-analyzer/disk_analyzer_cli.py" "$@"
WRAPPER
chmod +x "${INSTALL_DIR}/disk-analyzer"

echo ""
echo "✓ Installed successfully!"
echo ""

# Check if ~/.local/bin is in PATH
case ":${PATH}:" in
    *":${INSTALL_DIR}:"*)
        echo "Run 'disk-analyzer' to get started."
        ;;
    *)
        echo "Add ~/.local/bin to your PATH by adding this to your shell profile:"
        echo ""
        SHELL_NAME=$(basename "${SHELL}")
        case "${SHELL_NAME}" in
            zsh)
                echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc"
                echo "  source ~/.zshrc"
                ;;
            bash)
                echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
                echo "  source ~/.bashrc"
                ;;
            *)
                echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
                ;;
        esac
        echo ""
        echo "Then run 'disk-analyzer' to get started."
        ;;
esac

echo ""
echo "Config: ${CONFIG_DIR}/config.toml"
echo "Usage:  disk-analyzer          # interactive TUI"
echo "        disk-analyzer scan ~   # scan home directory"
echo "        disk-analyzer browse   # browse results"
