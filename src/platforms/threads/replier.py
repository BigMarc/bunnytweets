"""Auto-reply to mentions/activity on Threads.net using per-account templates."""

from __future__ import annotations

from loguru import logger

from src.core.database import Database
from src.platforms.threads.automation import ThreadsAutomation


class ThreadsReplier:
    """Handles auto-replying to mentions for a single Threads account."""

    def __init__(
        self,
        automation: ThreadsAutomation,
        database: Database,
        account_name: str,
        account_config: dict,
        notifier=None,
    ):
        self.auto = automation
        self.db = database
        self.account_name = account_name
        self.config = account_config
        self.notifier = notifier

    def run_reply_cycle(self) -> bool:
        """Check activity for mentions and reply. Returns True if a reply was made."""
        reply_cfg = self.config.get("reply_to_replies", {})
        if not reply_cfg.get("enabled", False):
            logger.info(f"[{self.account_name}] Auto-reply is not enabled")
            return False

        daily_limit = reply_cfg.get("daily_limit", 10)
        current_count = self.db.get_replies_today(self.account_name)

        if current_count >= daily_limit:
            logger.info(
                f"[{self.account_name}] Daily reply limit reached "
                f"({current_count}/{daily_limit})"
            )
            return False

        try:
            return self._do_reply(daily_limit, current_count)
        except Exception as exc:
            logger.error(f"[{self.account_name}] Reply cycle failed: {exc}")
            if self.notifier:
                self.notifier.send(
                    title="Reply Failed",
                    description=(
                        f"**{self.account_name}** Threads reply cycle error: "
                        f"{str(exc)[:200]}"
                    ),
                    color=0xFF0000,
                )
            raise

    def _do_reply(self, daily_limit: int, current_count: int) -> bool:
        template = self.db.get_random_reply_template(self.account_name)
        if not template:
            logger.debug(
                f"[{self.account_name}] No reply templates configured, skipping"
            )
            return False

        mentions = self.auto.get_notification_replies(limit=15)
        if not mentions:
            logger.debug(
                f"[{self.account_name}] No mentions found in Threads activity"
            )
            return False

        for mention in mentions:
            post_url = mention.get("url", "")
            reply_post_id = mention.get("tweet_id", "")
            if not post_url or not reply_post_id:
                continue

            if self.db.is_reply_tracked(self.account_name, reply_post_id):
                continue

            logger.info(
                f"[{self.account_name}] Replying to Threads mention {reply_post_id}"
            )
            success = self.auto.reply_to_tweet(post_url, template)

            if success:
                self.db.record_reply(
                    self.account_name,
                    original_tweet_id=reply_post_id,
                    reply_tweet_id=reply_post_id,
                )
                logger.info(
                    f"[{self.account_name}] Reply successful "
                    f"({current_count + 1}/{daily_limit} today)"
                )
                return True
            else:
                logger.warning(
                    f"[{self.account_name}] Failed to reply to {reply_post_id}"
                )
                self.db.record_reply(
                    self.account_name,
                    original_tweet_id=reply_post_id,
                    reply_tweet_id=reply_post_id,
                )

        logger.debug(
            f"[{self.account_name}] No eligible mentions to reply to this cycle"
        )
        return False
