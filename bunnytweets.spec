# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for BunnyTweets Desktop.

Build:
    pyinstaller bunnytweets.spec

The resulting executable lives in dist/BunnyTweets/ (one-dir mode) which keeps
startup fast and makes debugging easier than one-file mode.
"""

import os
import sys
from pathlib import Path

block_cipher = None

# Project root is where this spec file lives
ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Flask templates, static assets, and example configs
        (str(ROOT / "src" / "web" / "templates"), "src/web/templates"),
        (str(ROOT / "src" / "web" / "static"), "src/web/static"),
        (str(ROOT / "config" / "settings.yaml.example"), "config"),
        (str(ROOT / "config" / "accounts.yaml.example"), "config"),
    ],
    hiddenimports=[
        # Flask + Jinja
        "flask",
        "jinja2.ext",
        # SQLAlchemy dialects
        "sqlalchemy.dialects.sqlite",
        # APScheduler triggers
        "apscheduler.triggers.cron",
        "apscheduler.triggers.interval",
        "apscheduler.triggers.date",
        "apscheduler.jobstores.memory",
        "apscheduler.executors.pool",
        # Google API / Drive
        "googleapiclient",
        "google.auth.transport.requests",
        # pystray backends
        "pystray._darwin" if sys.platform == "darwin" else "pystray._win32",
        # Selenium
        "selenium.webdriver.chrome.service",
        "selenium.webdriver.chrome.options",
        # Project modules
        "src.core.config_loader",
        "src.core.database",
        "src.core.notifier",
        "src.core.logger",
        "src.web",
        "src.web.state",
        "src.web.routes",
        "src.web.routes.dashboard",
        "src.web.routes.settings",
        "src.web.routes.accounts",
        "src.web.routes.generator",
        "src.web.routes.logs",
        "src.web.routes.actions",
        "src.web.routes.api",
        "src.web.routes.analytics",
        "src.scheduler.job_manager",
        "src.scheduler.queue_handler",
        "src.twitter.automation",
        "src.twitter.poster",
        "src.twitter.retweeter",
        "src.twitter.replier",
        "src.twitter.human_simulator",
        "src.dolphin_anty.api_client",
        "src.dolphin_anty.profile_manager",
        "src.gologin.api_client",
        "src.google_drive.drive_client",
        "src.google_drive.file_monitor",
        "main",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "test",
        "unittest",
        "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BunnyTweets",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window on Windows; macOS uses .app bundle
    # icon="assets/icon.ico",  # Uncomment when a real .ico is available
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="BunnyTweets",
)

# macOS .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="BunnyTweets.app",
        # icon="assets/icon.icns",  # Uncomment when a real .icns is available
        bundle_identifier="com.bunnytweets.desktop",
        info_plist={
            "CFBundleName": "BunnyTweets",
            "CFBundleDisplayName": "BunnyTweets",
            "CFBundleVersion": "1.0.0",
            "CFBundleShortVersionString": "1.0.0",
            "LSUIElement": True,  # Hide from Dock (tray-only app)
        },
    )
