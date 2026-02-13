from __future__ import annotations

import io
from pathlib import Path

from loguru import logger
from PIL import Image

# Maximum Twitter media limits
MAX_IMAGE_SIZE_MB = 5
MAX_VIDEO_SIZE_MB = 512
MAX_GIF_SIZE_MB = 15

# Compression settings
_JPEG_QUALITY_START = 90
_JPEG_QUALITY_MIN = 40
_JPEG_QUALITY_STEP = 10
_MAX_DIMENSION = 4096  # resize long edge if above this

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov"}
GIF_EXTENSIONS = {".gif"}
TEXT_EXTENSIONS = {".txt"}
ALL_MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | GIF_EXTENSIONS


class MediaHandler:
    """Validates and prepares media files for Twitter upload."""

    @staticmethod
    def is_media_file(path: Path) -> bool:
        return path.suffix.lower() in ALL_MEDIA_EXTENSIONS

    @staticmethod
    def is_text_file(path: Path) -> bool:
        return path.suffix.lower() in TEXT_EXTENSIONS

    @staticmethod
    def validate_file(path: Path) -> bool:
        """Check that a file exists and is within Twitter's size limits."""
        if not path.exists():
            logger.warning(f"File does not exist: {path}")
            return False

        size_mb = path.stat().st_size / (1024 * 1024)
        ext = path.suffix.lower()

        if ext in IMAGE_EXTENSIONS:
            if size_mb > MAX_IMAGE_SIZE_MB:
                logger.warning(
                    f"Image too large ({size_mb:.1f} MB > {MAX_IMAGE_SIZE_MB} MB): {path}"
                )
                return False
            try:
                with Image.open(path) as img:
                    img.verify()
            except Exception as exc:
                logger.warning(f"Invalid image file {path}: {exc}")
                return False

        elif ext in GIF_EXTENSIONS:
            if size_mb > MAX_GIF_SIZE_MB:
                logger.warning(
                    f"GIF too large ({size_mb:.1f} MB > {MAX_GIF_SIZE_MB} MB): {path}"
                )
                return False

        elif ext in VIDEO_EXTENSIONS:
            if size_mb > MAX_VIDEO_SIZE_MB:
                logger.warning(
                    f"Video too large ({size_mb:.1f} MB > {MAX_VIDEO_SIZE_MB} MB): {path}"
                )
                return False

        else:
            logger.warning(f"Unsupported media type: {ext}")
            return False

        return True

    @staticmethod
    def compress_image(path: Path, max_size_mb: float = MAX_IMAGE_SIZE_MB) -> Path:
        """Compress an oversized image to fit under *max_size_mb*.

        Strategy: progressively lower JPEG quality.  If still too large,
        also scale down the dimensions.  Returns the (possibly new) path.
        """
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb <= max_size_mb:
            return path

        max_bytes = int(max_size_mb * 1024 * 1024)
        img = Image.open(path)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Cap extreme resolutions first
        w, h = img.size
        if max(w, h) > _MAX_DIMENSION:
            ratio = _MAX_DIMENSION / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
            logger.info(f"Resized {path.name} from {w}x{h} to {img.size[0]}x{img.size[1]}")

        # Try progressively lower JPEG quality
        quality = _JPEG_QUALITY_START
        while quality >= _JPEG_QUALITY_MIN:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            if buf.tell() <= max_bytes:
                break
            quality -= _JPEG_QUALITY_STEP

        # If still too large, scale down further
        scale = 0.8
        while buf.tell() > max_bytes and scale > 0.3:
            w, h = img.size
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=_JPEG_QUALITY_MIN, optimize=True)
            scale -= 0.1

        # Write result — keep the original path when already JPEG-compatible
        # to avoid case-sensitivity issues (e.g. .JPG → .jpg on macOS)
        if path.suffix.lower() in (".jpg", ".jpeg"):
            out_path = path
        else:
            out_path = path.with_suffix(".jpg")

        out_path.write_bytes(buf.getvalue())
        final_mb = out_path.stat().st_size / (1024 * 1024)
        logger.info(
            f"Compressed {path.name} ({size_mb:.1f} MB) -> "
            f"{out_path.name} ({final_mb:.1f} MB, q={quality})"
        )

        # Remove original if the output is a genuinely different file
        if out_path != path:
            path.unlink(missing_ok=True)

        return out_path

    @staticmethod
    def read_text_content(path: Path) -> str:
        """Read tweet text from a .txt file."""
        try:
            return path.read_text(encoding="utf-8").strip()
        except Exception as exc:
            logger.warning(f"Could not read text file {path}: {exc}")
            return ""

    @staticmethod
    def group_files(files: list[Path]) -> list[dict]:
        """Group downloaded files into postable items.

        Each item has:
          - media: list[Path]  (image/video files)
          - text: str          (from .txt file or empty)

        Grouping logic:
          - Files with the same stem (filename without extension) are grouped.
          - e.g. post1.jpg + post1.txt -> one post with image and text.
          - Standalone media files become their own post.
        """
        by_stem: dict[str, dict] = {}
        for f in files:
            stem = f.stem
            if stem not in by_stem:
                by_stem[stem] = {"media": [], "text": ""}
            if f.suffix.lower() in TEXT_EXTENSIONS:
                by_stem[stem]["text"] = f.read_text(encoding="utf-8").strip()
            elif f.suffix.lower() in ALL_MEDIA_EXTENSIONS:
                by_stem[stem]["media"].append(f)

        # Only return items that have at least one media file
        return [item for item in by_stem.values() if item["media"]]
