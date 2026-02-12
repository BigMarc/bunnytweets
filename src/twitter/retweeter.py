"""High-level retweeting logic: pick target profiles, avoid duplicates, respect limits."""

from __future__ import annotations

from datetime import datetime

from loguru import logger

from src.core.database import Database
from src.twitter.automation import TwitterAutomation


class TwitterRetweeter:
    """Handles the daily retweet quota for a single account."""

    def __init__(
        self,
        automation: TwitterAutomation,
        database: Database,
        account_name: str,
        account_config: dict,
    ):
        self.auto = automation
        self.db = database
        self.account_name = account_name
        self.config = account_config

    def run_retweet_cycle(self) -> bool:
        """Perform one retweet if quota allows. Returns True if a retweet was made."""
        rt_cfg = self.config.get("retweeting", {})
        if not rt_cfg.get("enabled", False):
            return False

        daily_limit = rt_cfg.get("daily_limit", 3)
        current_count = self.db.get_retweets_today(self.account_name)

        if current_count >= daily_limit:
            logger.debug(
                f"[{self.account_name}] Daily retweet limit reached ({current_count}/{daily_limit})"
            )
            return False

        targets = rt_cfg.get("target_profiles", [])
        strategy = rt_cfg.get("strategy", "latest")

        # Sort by priority
        targets = sorted(targets, key=lambda t: t.get("priority", 99))

        for target in targets:
            username = target.get("username", "")
            if not username:
                continue

            tweet_urls = self.auto.get_latest_tweet_urls(username, limit=10)
            if not tweet_urls:
                logger.debug(f"[{self.account_name}] No tweets found for {username}")
                continue

            for url in tweet_urls:
                tweet_id = self.auto.get_tweet_id_from_url(url)
                if not tweet_id:
                    continue

                if self.db.is_already_retweeted(self.account_name, tweet_id):
                    logger.debug(
                        f"[{self.account_name}] Already retweeted {tweet_id}, skipping"
                    )
                    continue

                # Attempt the retweet
                logger.info(
                    f"[{self.account_name}] Retweeting {username} tweet {tweet_id}"
                )
                success = self.auto.retweet(url)

                if success:
                    self.db.record_retweet(self.account_name, username, tweet_id)
                    self.db.increment_retweets_today(self.account_name)
                    self.db.update_account_status(
                        self.account_name,
                        last_retweet=datetime.utcnow(),
                        status="idle",
                    )
                    logger.info(
                        f"[{self.account_name}] Retweet successful "
                        f"({current_count + 1}/{daily_limit} today)"
                    )
                    return True
                else:
                    logger.warning(
                        f"[{self.account_name}] Failed to retweet {tweet_id}"
                    )

        logger.debug(f"[{self.account_name}] No eligible tweets to retweet this cycle")
        return False
