#!/usr/bin/env bash
# Build BunnyTweets desktop app for the current platform.
#
# Usage:
#   ./scripts/build.sh          Build the app
#   ./scripts/build.sh clean    Remove build artifacts
#
# Prerequisites:
#   pip install pyinstaller pystray
#
# Output:
#   macOS:   dist/BunnyTweets.app
#   Linux:   dist/BunnyTweets/BunnyTweets
#   Windows: Use scripts/build.bat instead

set -euo pipefail
cd "$(dirname "$0")/.."

if [ "${1:-}" = "clean" ]; then
    echo "Cleaning build artifacts..."
    rm -rf build/ dist/ *.spec.bak
    echo "Done."
    exit 0
fi

echo "========================================"
echo "  BunnyTweets Desktop — Build"
echo "========================================"

# Check for PyInstaller
if ! command -v pyinstaller &>/dev/null; then
    echo "ERROR: pyinstaller not found. Install it with:"
    echo "  pip install pyinstaller"
    exit 1
fi

# Check for pystray
python -c "import pystray" 2>/dev/null || {
    echo "ERROR: pystray not found. Install it with:"
    echo "  pip install pystray"
    exit 1
}

echo "Building with PyInstaller..."
pyinstaller bunnytweets.spec --noconfirm

OS=$(uname -s)
if [ "$OS" = "Darwin" ]; then
    echo ""
    echo "Build complete!"
    echo "  App:   dist/BunnyTweets.app"
    echo ""
    echo "To install, drag BunnyTweets.app to /Applications."
    echo "To create a .dmg:"
    echo "  hdiutil create -volname BunnyTweets -srcfolder dist/BunnyTweets.app -ov dist/BunnyTweets.dmg"
else
    echo ""
    echo "Build complete!"
    echo "  Binary: dist/BunnyTweets/BunnyTweets"
    echo ""
    echo "Run with: ./dist/BunnyTweets/BunnyTweets"
fi
