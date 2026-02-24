"""High-level posting logic: pulls from Drive, rotates content, picks titles from categories."""

from __future__ import annotations

import random
import time
from datetime import datetime
from pathlib import Path

from loguru import logger

from src.core.database import Database
from src.google_drive.file_monitor import FileMonitor
from src.google_drive.media_handler import MediaHandler
from src.twitter.automation import TwitterAutomation


class TwitterPoster:
    """Orchestrates downloading from Drive and posting to Twitter.

    Content rotation: all files in the Drive folder are candidates.  The
    poster picks the file with the lowest use_count (preferring never-used
    files) and increments the counter after each post.

    Title selection: a random title is picked from the account's assigned
    title categories (always including "Global").

    CTA self-comment: after posting, waits ~1 hour then comes back and
    comments with a random CTA text under the post.
    """

    def __init__(
        self,
        automation: TwitterAutomation,
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
        """Pick the least-used media file, pair with a random title, and post.

        If CTA texts are configured for this account the poster will wait
        ~1 hour then reply to its own tweet with a random CTA.

        Returns True if a tweet was posted.
        """
        logger.info(f"[{self.account_name}] Starting posting cycle")

        drive_cfg = self.config.get("google_drive", {})
        folder_id = drive_cfg.get("folder_id")
        file_types = drive_cfg.get("file_types", [])

        if not folder_id:
            logger.warning(f"[{self.account_name}] No Google Drive folder_id configured — skipping post")
            return False

        # List ALL files in the folder (not just new ones)
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
            logger.info(f"[{self.account_name}] No files found in Drive folder — nothing to post")
            return False

        # Separate media files from text files
        media_files = [
            f for f in all_files
            if not f["name"].lower().endswith(".txt")
        ]
        if not media_files:
            logger.info(
                f"[{self.account_name}] Drive folder has {len(all_files)} file(s) but none "
                "are media (only .txt found) — nothing to post"
            )
            return False

        # Pick the least-used file for this account
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

        # Download the chosen file
        try:
            local_path = self.monitor.download_file(self.account_name, chosen_meta)
        except Exception as exc:
            logger.error(
                f"[{self.account_name}] Failed to download {chosen_meta['name']}: {exc}"
            )
            return False

        # Convert .mov to .mp4 for Twitter compatibility
        if local_path.suffix.lower() == ".mov":
            local_path = self.media_handler.convert_mov_to_mp4(local_path)

        # Auto-compress oversized images
        if local_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            local_path = self.media_handler.compress_image(local_path)

        # Validate media
        if not self.media_handler.validate_file(local_path):
            logger.warning(
                f"[{self.account_name}] Invalid media file: {local_path.name}"
            )
            self._cleanup(local_path)
            return False

        # Pick a title from the account's assigned categories
        text = self._pick_title()

        logger.info(
            f"[{self.account_name}] Posting tweet with '{chosen_meta['name']}'"
            + (f" + title ({len(text)} chars)" if text else " (no title)")
        )
        success = self.auto.compose_tweet(text=text, media_files=[local_path])

        # Record the usage
        status = "success" if success else "failed"
        self.db.increment_file_use(
            self.account_name, chosen_id, chosen_meta["name"],
            status=status,
        )

        if success:
            self.db.update_account_status(
                self.account_name, last_post=datetime.utcnow(), status="idle"
            )

            # Schedule a CTA self-comment after ~1 hour
            self._maybe_schedule_cta()
        else:
            if self.notifier:
                self.notifier.alert_post_failed(
                    self.account_name, f"compose_tweet returned False for '{chosen_meta['name']}'"
                )

        self._cleanup(local_path)
        return success

    def run_cta_comment(self) -> bool:
        """Find the account's latest tweet and comment a CTA text under it.

        Called by the scheduler ~1 hour after posting.
        """
        cta_text = self.db.get_random_cta(self.account_name)
        if not cta_text:
            logger.debug(f"[{self.account_name}] No CTA texts configured, skipping")
            return False

        username = self.config.get("twitter", {}).get("username", "")
        if not username:
            return False

        tweet_urls = self.auto.get_latest_tweet_urls(username, limit=1)
        if not tweet_urls:
            logger.warning(f"[{self.account_name}] No tweets found for CTA comment")
            return False

        tweet_url = tweet_urls[0]
        logger.info(
            f"[{self.account_name}] Commenting CTA on own tweet: {tweet_url}"
        )
        success = self.auto.reply_to_tweet(tweet_url, cta_text)
        if success:
            self.db.update_account_status(
                self.account_name, last_cta=datetime.utcnow()
            )
        return success

    def _pick_title(self) -> str:
        """Pick the least-used title from the account's assigned categories.

        Uses rotation tracking so every title gets equal airtime before
        any repeats.  Falls back to posting.default_text if no titles exist.
        """
        posting_cfg = self.config.get("posting", {})
        categories = posting_cfg.get("title_categories", [])

        if categories:
            title = self.db.get_random_title(categories, account_name=self.account_name)
            if title:
                self.db.increment_title_use(self.account_name, title, categories)
                return title

        # Fallback to default_text
        return posting_cfg.get("default_text", "")

    def _maybe_schedule_cta(self) -> None:
        """If the account has CTA texts, flag that a CTA comment is pending.

        The actual scheduling is done by the Application class which checks
        for this flag and enqueues a delayed task (~1 hour after posting).
        """
        ctas = self.db.get_cta_texts(self.account_name)
        if ctas:
            self.db.update_account_status(
                self.account_name, cta_pending=1
            )

    @staticmethod
    def _cleanup(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
