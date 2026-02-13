"""High-level repost logic for Threads.net — equivalent of TwitterRetweeter.

Picks target profiles, avoids duplicates, respects daily limits.
Uses the same database retweet tracking (account_name + tweet/post ID).
"""

from __future__ import annotations

from datetime import datetime

from loguru import logger

from src.core.database import Database
from src.platforms.threads.automation import ThreadsAutomation


class ThreadsReposter:
    """Handles the daily repost quota for a single Threads account."""

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

    def run_retweet_cycle(self) -> bool:
        """Perform one repost if quota allows. Named for scheduler API parity."""
        # Threads uses "reposting" config key
        rt_cfg = self.config.get("reposting", {})
        if not rt_cfg.get("enabled", False):
            logger.info(f"[{self.account_name}] Reposting is not enabled")
            return False

        daily_limit = rt_cfg.get("max_per_day", 5)
        current_count = self.db.get_retweets_today(self.account_name)

        if current_count >= daily_limit:
            logger.info(
                f"[{self.account_name}] Daily repost limit reached "
                f"({current_count}/{daily_limit})"
            )
            return False

        try:
            return self._do_repost(daily_limit, current_count)
        except Exception as exc:
            logger.error(f"[{self.account_name}] Repost cycle failed: {exc}")
            if self.notifier:
                self.notifier.alert_retweet_failed(
                    self.account_name, f"Unexpected error: {str(exc)[:200]}"
                )
            raise

    def _do_repost(self, daily_limit: int, current_count: int) -> bool:
        rt_cfg = self.config.get("reposting", {})
        targets = list(rt_cfg.get("targets", []))

        # Merge global targets
        own_username = self.config.get("threads", {}).get("username", "")
        own_handle = f"@{own_username.lstrip('@')}" if own_username else ""
        existing = {t.lower() if isinstance(t, str) else t.get("username", "").lower()
                    for t in targets}

        global_usernames = self.db.get_global_target_usernames()
        for g_user in global_usernames:
            if own_handle and g_user.lower() == own_handle.lower():
                continue
            if g_user.lower() not in existing:
                targets.append(g_user)

        for target in targets:
            username = target if isinstance(target, str) else target.get("username", "")
            if not username:
                continue

            post_urls = self.auto.get_latest_tweet_urls(username, limit=10)
            if not post_urls:
                logger.debug(
                    f"[{self.account_name}] No posts found for {username} on Threads"
                )
                continue

            for url in post_urls:
                post_id = self.auto.get_tweet_id_from_url(url)
                if not post_id:
                    continue

                if self.db.is_already_retweeted(self.account_name, post_id):
                    logger.debug(
                        f"[{self.account_name}] Already reposted {post_id}, skipping"
                    )
                    continue

                logger.info(
                    f"[{self.account_name}] Reposting {username} post {post_id}"
                )
                success = self.auto.retweet(url)

                if success:
                    self.db.record_retweet(self.account_name, username, post_id)
                    self.db.increment_retweets_today(self.account_name)
                    self.db.update_account_status(
                        self.account_name,
                        last_retweet=datetime.utcnow(),
                        status="idle",
                    )
                    logger.info(
                        f"[{self.account_name}] Repost successful "
                        f"({current_count + 1}/{daily_limit} today)"
                    )
                    return True
                else:
                    logger.warning(
                        f"[{self.account_name}] Failed to repost {post_id}"
                    )
                    if self.notifier:
                        self.notifier.alert_retweet_failed(
                            self.account_name,
                            f"Failed to repost {post_id} from {username} on Threads",
                        )

        logger.debug(
            f"[{self.account_name}] No eligible posts to repost this cycle"
        )
        return False
