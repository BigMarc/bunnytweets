from pathlib import Path

from loguru import logger
from PIL import Image

# Maximum Twitter media limits
MAX_IMAGE_SIZE_MB = 5
MAX_VIDEO_SIZE_MB = 512
MAX_GIF_SIZE_MB = 15

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
