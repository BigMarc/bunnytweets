#!/usr/bin/env python3
"""BunnyTweets Desktop — system tray launcher for the web dashboard + engine.

Starts the Flask dashboard in a background thread and shows a system tray icon
with controls for managing the bot.  Double-click the icon (or use the menu)
to open the dashboard in your default browser.

Usage:
    python desktop.py              Launch with system tray
    python desktop.py --headless   Launch without tray (CI / Docker)
"""

from __future__ import annotations

import argparse
import os
import platform
import signal
import sys
import threading
import webbrowser
from pathlib import Path

# Pillow is already in requirements — used to generate the tray icon
from PIL import Image, ImageDraw, ImageFont

PORT = 8080
DASHBOARD_URL = f"http://localhost:{PORT}"


# ------------------------------------------------------------------
# Icon generation (no external asset file required)
# ------------------------------------------------------------------
def _create_icon_image(size: int = 64) -> Image.Image:
    """Generate a simple BT (BunnyTweets) icon programmatically."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Circle background
    margin = 2
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=(99, 102, 241),  # Indigo
    )

    # "BT" text
    try:
        font = ImageFont.truetype("arial.ttf", size // 3)
    except (IOError, OSError):
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size // 3)
        except (IOError, OSError):
            font = ImageFont.load_default()

    text = "BT"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) // 2
    y = (size - th) // 2 - bbox[1]
    draw.text((x, y), text, fill="white", font=font)

    return img


# ------------------------------------------------------------------
# Flask dashboard thread
# ------------------------------------------------------------------
_flask_app = None
_app_state = None


def _start_flask():
    """Start the Flask web dashboard in the calling thread (blocking)."""
    global _flask_app, _app_state

    # Ensure project root is on sys.path
    project_root = str(Path(__file__).resolve().parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from src.core.config_loader import ConfigLoader
    from src.core.database import Database
    from src.web import create_app

    config = ConfigLoader()
    db = Database(str(config.resolve_path(config.database_path)))
    _flask_app = create_app(config, db)
    _app_state = _flask_app.config["APP_STATE"]

    # Disable Flask's reloader (incompatible with threads)
    _flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


def _start_flask_thread() -> threading.Thread:
    """Launch Flask in a daemon thread and return the thread handle."""
    t = threading.Thread(target=_start_flask, daemon=True, name="flask-dashboard")
    t.start()
    return t


# ------------------------------------------------------------------
# System tray
# ------------------------------------------------------------------
def _build_tray():
    """Build and return the pystray Icon. Runs on the main thread."""
    import pystray

    def on_open(icon, item):
        webbrowser.open(DASHBOARD_URL)

    def on_start_engine(icon, item):
        if _app_state and not _app_state.engine_running:
            _app_state.start_engine()
            icon.notify("Engine starting…", "BunnyTweets")

    def on_stop_engine(icon, item):
        if _app_state and _app_state.engine_running:
            _app_state.stop_engine()
            icon.notify("Engine stopping…", "BunnyTweets")

    def engine_status_text(item):
        if _app_state is None:
            return "Engine: initializing"
        return f"Engine: {_app_state.engine_status}"

    def on_quit(icon, item):
        if _app_state and _app_state.engine_running:
            _app_state.stop_engine()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open Dashboard", on_open, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(engine_status_text, None, enabled=False),
        pystray.MenuItem("Start Engine", on_start_engine),
        pystray.MenuItem("Stop Engine", on_stop_engine),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )

    icon = pystray.Icon(
        name="BunnyTweets",
        icon=_create_icon_image(64),
        title="BunnyTweets",
        menu=menu,
    )
    return icon


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="BunnyTweets Desktop")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without system tray (e.g. in Docker / CI)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Web dashboard port (default: 8080)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't auto-open the browser on startup",
    )
    args = parser.parse_args()

    global PORT, DASHBOARD_URL
    PORT = args.port
    DASHBOARD_URL = f"http://localhost:{PORT}"

    print(f"\n  BunnyTweets Desktop")
    print(f"  Dashboard: {DASHBOARD_URL}")
    print(f"  System tray: {'disabled' if args.headless else 'enabled'}\n")

    # Start Flask in background
    flask_thread = _start_flask_thread()

    # Give Flask a moment to bind the port
    import time
    time.sleep(1.5)

    # Auto-open browser
    if not args.no_browser:
        webbrowser.open(DASHBOARD_URL)

    if args.headless:
        # No tray — block until Ctrl+C
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        try:
            flask_thread.join()
        except KeyboardInterrupt:
            print("\nShutting down…")
            if _app_state and _app_state.engine_running:
                _app_state.stop_engine()
    else:
        # System tray on main thread (required for macOS AppKit)
        try:
            icon = _build_tray()
            icon.run()
        except KeyboardInterrupt:
            pass
        finally:
            if _app_state and _app_state.engine_running:
                _app_state.stop_engine()


if __name__ == "__main__":
    main()
