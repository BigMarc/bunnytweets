"""High-level posting logic: pulls from Drive queue and posts via Selenium."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from loguru import logger

from src.core.database import Database
from src.google_drive.file_monitor import FileMonitor
from src.google_drive.media_handler import MediaHandler
from src.twitter.automation import TwitterAutomation


class TwitterPoster:
    """Orchestrates downloading from Drive and posting to Twitter."""

    def __init__(
        self,
        automation: TwitterAutomation,
        file_monitor: FileMonitor,
        database: Database,
        account_name: str,
        account_config: dict,
    ):
        self.auto = automation
        self.monitor = file_monitor
        self.db = database
        self.account_name = account_name
        self.config = account_config
        self.media_handler = MediaHandler()

    def run_posting_cycle(self) -> bool:
        """Check for new files, download, and post a single item.

        Returns True if a tweet was posted.
        """
        drive_cfg = self.config.get("google_drive", {})
        folder_id = drive_cfg.get("folder_id")
        file_types = drive_cfg.get("file_types", [])

        if not folder_id:
            logger.warning(f"[{self.account_name}] No Google Drive folder_id configured")
            return False

        new_files = self.monitor.check_for_new_files(
            self.account_name, folder_id, file_types
        )
        if not new_files:
            logger.debug(f"[{self.account_name}] No new files to post")
            return False

        # Download all new files
        downloaded: list[Path] = []
        file_metas: list[dict] = []
        for fmeta in new_files:
            try:
                local = self.monitor.download_file(self.account_name, fmeta)
                downloaded.append(local)
                file_metas.append(fmeta)
            except Exception as exc:
                logger.error(
                    f"[{self.account_name}] Failed to download {fmeta['name']}: {exc}"
                )

        if not downloaded:
            return False

        # Group files into postable items
        items = self.media_handler.group_files(downloaded)
        if not items:
            # Files were all text or invalid
            for fm in file_metas:
                self.monitor.mark_processed(self.account_name, fm, status="failed")
            return False

        # Post the first available item
        item = items[0]
        media_paths: list[Path] = []
        for mp in item["media"]:
            if self.media_handler.validate_file(mp):
                media_paths.append(mp)
            else:
                logger.warning(
                    f"[{self.account_name}] Skipping invalid media: {mp.name}"
                )

        if not media_paths:
            logger.warning(f"[{self.account_name}] No valid media files to post")
            for fm in file_metas:
                self.monitor.mark_processed(self.account_name, fm, status="failed")
            return False

        text = item["text"]
        if not text:
            text = self.config.get("posting", {}).get("default_text", "")

        logger.info(
            f"[{self.account_name}] Posting tweet with {len(media_paths)} media file(s)"
        )
        success = self.auto.compose_tweet(text=text, media_files=media_paths)

        # Mark all files for this batch as processed
        status = "success" if success else "failed"
        for fm in file_metas:
            self.monitor.mark_processed(self.account_name, fm, status=status)

        if success:
            self.db.update_account_status(
                self.account_name, last_post=datetime.utcnow(), status="idle"
            )

        # Clean up downloaded files
        for p in downloaded:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

        return success
