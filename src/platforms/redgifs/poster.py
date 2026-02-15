"""High-level posting logic for RedGifs accounts.

Mirrors ThreadsPoster — pulls media from Google Drive, rotates content
via least-used-file, picks titles, and uploads with tags.

RedGifs does not support CTA self-comments, so run_cta_comment() and
_maybe_schedule_cta() are intentionally omitted.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from loguru import logger

from src.core.database import Database
from src.google_drive.file_monitor import FileMonitor
from src.google_drive.media_handler import MediaHandler
from src.platforms.redgifs.automation import RedGifsAutomation


class RedGifsPoster:
    """Orchestrates downloading from Drive and uploading to RedGifs."""

    def __init__(
        self,
        automation: RedGifsAutomation,
        file_monitor: FileMonitor,
        database: Database,
        account_name: str,
        account_config: dict,
        notifier=None,
    ):
        self.auto = automation
        self.monitor = file_monitor
        self.db = database
        self.account_name = account_name
        self.config = account_config
        self.media_handler = MediaHandler()
        self.notifier = notifier

    def run_posting_cycle(self) -> bool:
        """Pick the least-used media file, pair with tags + title, and upload."""
        logger.info(f"[{self.account_name}] Starting RedGifs posting cycle")

        drive_cfg = self.config.get("google_drive", {})
        folder_id = drive_cfg.get("folder_id")
        file_types = drive_cfg.get("file_types", [])

        if not folder_id:
            logger.warning(
                f"[{self.account_name}] No Google Drive folder_id configured — skipping post"
            )
            return False

        try:
            all_files = self.monitor.list_all_files(
                self.account_name, folder_id, file_types
            )
        except Exception as exc:
            logger.warning(
                f"[{self.account_name}] Could not reach Google Drive: {exc}. "
                "Will retry on the next cycle."
            )
            if self.notifier:
                self.notifier.alert_drive_unreachable(self.account_name, str(exc))
            return False

        if not all_files:
            logger.info(
                f"[{self.account_name}] No files found in Drive folder — nothing to post"
            )
            return False

        media_files = [
            f for f in all_files if not f["name"].lower().endswith(".txt")
        ]
        if not media_files:
            logger.info(
                f"[{self.account_name}] Drive folder has {len(all_files)} file(s) "
                "but none are media (only .txt found) — nothing to post"
            )
            return False

        file_ids = [f["id"] for f in media_files]
        chosen_id = self.db.get_least_used_file(self.account_name, file_ids)
        if not chosen_id:
            return False

        chosen_meta = next(f for f in media_files if f["id"] == chosen_id)
        use_count = self.db.get_file_use_count(self.account_name, chosen_id)

        logger.info(
            f"[{self.account_name}] Selected '{chosen_meta['name']}' "
            f"(used {use_count} time(s) before)"
        )

        try:
            local_path = self.monitor.download_file(self.account_name, chosen_meta)
        except Exception as exc:
            logger.error(
                f"[{self.account_name}] Failed to download {chosen_meta['name']}: {exc}"
            )
            return False

        # Convert .mov to .mp4 for compatibility
        if local_path.suffix.lower() == ".mov":
            local_path = self.media_handler.convert_mov_to_mp4(local_path)

        # Auto-compress oversized images
        if local_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            local_path = self.media_handler.compress_image(local_path)

        if not self.media_handler.validate_file(local_path):
            logger.warning(
                f"[{self.account_name}] Invalid media file: {local_path.name}"
            )
            self._cleanup(local_path)
            return False

        tags = self._get_tags()
        title = self._pick_title()
        sound_on = self.config.get("redgifs", {}).get("sound_on", True)

        logger.info(
            f"[{self.account_name}] Uploading to RedGifs: '{chosen_meta['name']}'"
            + (f" + {len(tags)} tag(s)" if tags else " (no tags)")
            + (f" + title ({len(title)} chars)" if title else "")
        )
        result_url = self.auto.upload_content(
            media_file=local_path,
            tags=tags,
            title=title,
            sound_on=sound_on,
        )

        success = result_url is not None
        status = "success" if success else "failed"
        self.db.increment_file_use(
            self.account_name,
            chosen_id,
            chosen_meta["name"],
            tweet_id=result_url,
            status=status,
        )

        if success:
            self.db.update_account_status(
                self.account_name, last_post=datetime.utcnow(), status="idle"
            )
        else:
            if self.notifier:
                self.notifier.alert_post_failed(
                    self.account_name,
                    f"upload_content returned None for '{chosen_meta['name']}' on RedGifs",
                )

        self._cleanup(local_path)
        return success

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_tags(self) -> list[str]:
        """Get tags for the upload from the RedGifs-specific config."""
        redgifs_cfg = self.config.get("redgifs", {})
        return list(redgifs_cfg.get("default_tags", []))

    def _pick_title(self) -> str:
        """Pick a random title from the account's assigned categories."""
        posting_cfg = self.config.get("posting", {})
        categories = posting_cfg.get("title_categories", [])
        if categories:
            title = self.db.get_random_title(categories)
            if title:
                return title
        return posting_cfg.get("default_text", "")

    @staticmethod
    def _cleanup(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
