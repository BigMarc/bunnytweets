"""Log viewer routes."""

from __future__ import annotations

import os
from pathlib import Path

from flask import Blueprint, render_template, request, jsonify, current_app

bp = Blueprint("logs", __name__)


@bp.route("/")
def index():
    state = current_app.config["APP_STATE"]
    log_dir = state.log_dir
    files = _list_log_files(log_dir)

    selected = request.args.get("file", "")
    if not selected and files:
        selected = files[0]["name"]

    content = ""
    if selected:
        content = _read_last_lines(log_dir / selected, 200)

    return render_template(
        "logs.html",
        files=files,
        selected=selected,
        content=content,
    )


@bp.route("/api/files")
def api_files():
    state = current_app.config["APP_STATE"]
    files = _list_log_files(state.log_dir)
    return jsonify(files)


@bp.route("/api/tail")
def api_tail():
    state = current_app.config["APP_STATE"]
    log_dir = state.log_dir

    filename = request.args.get("file", "")
    lines = int(request.args.get("lines", "200"))
    offset = int(request.args.get("offset", "0"))

    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400

    filepath = log_dir / filename
    if not filepath.exists() or not filepath.is_file():
        return jsonify({"error": "File not found"}), 404

    # Verify file is within log directory
    try:
        filepath.resolve().relative_to(log_dir.resolve())
    except ValueError:
        return jsonify({"error": "Access denied"}), 403

    file_size = filepath.stat().st_size

    if offset > 0 and offset <= file_size:
        # Incremental read from offset
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            content = f.read()
        new_offset = file_size
    elif offset == 0:
        # Initial load: read last N lines
        content = _read_last_lines(filepath, lines)
        new_offset = file_size
    else:
        # File was truncated/rotated, re-read
        content = _read_last_lines(filepath, lines)
        new_offset = file_size

    return jsonify({
        "content": content,
        "offset": new_offset,
        "size": file_size,
    })


def _list_log_files(log_dir: Path) -> list[dict]:
    """List log files sorted by modification time (newest first)."""
    if not log_dir.exists():
        return []

    files = []
    for f in log_dir.iterdir():
        if f.suffix == ".log" and f.is_file():
            is_main = f.name.startswith("automation_")
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "modified": f.stat().st_mtime,
                "category": "main" if is_main else "account",
            })

    files.sort(key=lambda x: x["modified"], reverse=True)
    return files


def _read_last_lines(filepath: Path, n: int) -> str:
    """Read the last N lines of a file efficiently."""
    if not filepath.exists():
        return ""

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            # For smaller files, just read all
            if filepath.stat().st_size < 1_000_000:
                lines = f.readlines()
                return "".join(lines[-n:])

            # For larger files, seek from end
            f.seek(0, 2)
            file_size = f.tell()
            block_size = 8192
            blocks = []
            remaining = file_size

            while remaining > 0 and len(blocks) * block_size < n * 200:
                read_size = min(block_size, remaining)
                remaining -= read_size
                f.seek(remaining)
                blocks.insert(0, f.read(read_size))

            text = "".join(blocks)
            lines = text.splitlines(True)
            return "".join(lines[-n:])
    except Exception:
        return ""
