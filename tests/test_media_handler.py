"""Tests for the MediaHandler file grouping and validation logic."""

import tempfile
from pathlib import Path

import pytest

from src.google_drive.media_handler import MediaHandler


@pytest.fixture
def handler():
    return MediaHandler()


class TestIsMediaFile:
    def test_image_extensions(self, handler):
        for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
            assert handler.is_media_file(Path(f"test{ext}"))

    def test_video_extensions(self, handler):
        for ext in [".mp4", ".mov"]:
            assert handler.is_media_file(Path(f"test{ext}"))

    def test_non_media(self, handler):
        assert not handler.is_media_file(Path("test.txt"))
        assert not handler.is_media_file(Path("test.pdf"))


class TestGroupFiles:
    def test_single_image(self, handler):
        files = [Path("post1.jpg")]
        groups = handler.group_files(files)
        assert len(groups) == 1
        assert groups[0]["media"] == [Path("post1.jpg")]
        assert groups[0]["text"] == ""

    def test_image_with_text(self, handler, tmp_path):
        img = tmp_path / "mypost.png"
        img.write_bytes(b"fake")
        txt = tmp_path / "mypost.txt"
        txt.write_text("Hello world!", encoding="utf-8")
        groups = handler.group_files([img, txt])
        assert len(groups) == 1
        assert len(groups[0]["media"]) == 1
        assert groups[0]["text"] == "Hello world!"

    def test_multiple_stems(self, handler, tmp_path):
        a = tmp_path / "first.jpg"
        a.write_bytes(b"img")
        b = tmp_path / "second.mp4"
        b.write_bytes(b"vid")
        groups = handler.group_files([a, b])
        assert len(groups) == 2

    def test_text_only_excluded(self, handler, tmp_path):
        txt = tmp_path / "note.txt"
        txt.write_text("just text", encoding="utf-8")
        groups = handler.group_files([txt])
        assert len(groups) == 0  # no media -> no post


class TestValidateFile:
    def test_missing_file(self, handler):
        assert not handler.validate_file(Path("/nonexistent/file.jpg"))

    def test_valid_small_image(self, handler, tmp_path):
        # Create a minimal valid JPEG
        from PIL import Image
        img = Image.new("RGB", (10, 10), "red")
        path = tmp_path / "small.jpg"
        img.save(path)
        assert handler.validate_file(path)

    def test_oversized_image(self, handler, tmp_path):
        path = tmp_path / "big.jpg"
        # Create a file > 5 MB of zeros (won't be valid image but test size check first)
        path.write_bytes(b"\x00" * (6 * 1024 * 1024))
        assert not handler.validate_file(path)
