"""Human-like browsing simulation for RedGifs.com.

Mirrors the Threads HumanSimulator — scrolls the feed, likes posts,
dwells on content (simulating watching videos), visits browse/discover,
with configurable durations and daily limits.
"""

from __future__ import annotations

import random
import time
from datetime import date

from loguru import logger

from src.core.database import Database
from src.platforms.redgifs.automation import RedGifsAutomation

DEFAULT_ACTION_WEIGHTS = {
    "scroll": 40,
    "view_content": 25,
    "like": 15,
    "explore": 20,
}


class RedGifsHumanSimulator:
    """Simulates natural browsing behaviour for a single RedGifs account."""

    def __init__(
        self,
        automation: RedGifsAutomation,
        database: Database,
        account_name: str,
        account_config: dict,
    ):
        self.auto = automation
        self.db = database
        self.account_name = account_name
        self.config = account_config

    def run_session(self) -> dict:
        """Run a full human-simulation session."""
        sim_cfg = self.config.get("human_simulation", {})
        if not sim_cfg.get("enabled", False):
            logger.info(
                f"[{self.account_name}] Human simulation is not enabled"
            )
            return {}

        duration_min = sim_cfg.get("session_duration_min", 30)
        duration_max = sim_cfg.get("session_duration_max", 60)
        session_minutes = random.randint(duration_min, duration_max)

        daily_likes_limit = sim_cfg.get("daily_likes_limit", 30)
        daily_sessions_limit = sim_cfg.get("daily_sessions_limit", 2)

        sessions_today = self._get_sessions_today()
        if sessions_today >= daily_sessions_limit:
            logger.info(
                f"[{self.account_name}] Daily session limit reached "
                f"({sessions_today}/{daily_sessions_limit}), skipping"
            )
            return {}

        likes_today = self._get_likes_today()
        likes_remaining = max(0, daily_likes_limit - likes_today)

        weights = dict(DEFAULT_ACTION_WEIGHTS)
        custom_weights = sim_cfg.get("action_weights", {})
        weights.update(custom_weights)

        if likes_remaining <= 0:
            weights.pop("like", None)

        logger.info(
            f"[{self.account_name}] Starting RedGifs simulation session "
            f"(~{session_minutes} min, {likes_remaining} likes remaining)"
        )

        self.db.update_account_status(self.account_name, status="browsing")

        summary = {
            "scrolls": 0,
            "likes": 0,
            "content_viewed": 0,
            "explore_visits": 0,
            "duration_minutes": 0,
        }
        session_likes = 0

        start = time.monotonic()
        end_time = start + session_minutes * 60

        try:
            self.auto.navigate_to_home()
            self.auto.dismiss_popups()
        except Exception as exc:
            logger.error(f"[{self.account_name}] Could not navigate home: {exc}")
            return summary

        while time.monotonic() < end_time:
            action = self._pick_action(weights)

            try:
                if action == "scroll":
                    count = random.randint(1, 4)
                    self.auto.scroll_feed(scroll_count=count)
                    summary["scrolls"] += count

                elif action == "view_content":
                    # Dwell on current content as if watching a video
                    dwell = random.uniform(5.0, 20.0)
                    time.sleep(dwell)
                    self.auto.scroll_feed(scroll_count=1)
                    summary["scrolls"] += 1
                    summary["content_viewed"] += 1

                elif action == "like":
                    if session_likes < likes_remaining:
                        if self.auto.like_post_on_page():
                            summary["likes"] += 1
                            session_likes += 1
                            if session_likes >= likes_remaining:
                                weights.pop("like", None)
                    self.auto.scroll_feed(scroll_count=random.randint(1, 2))
                    summary["scrolls"] += 1

                elif action == "explore":
                    self.auto.navigate_explore()
                    summary["explore_visits"] += 1
                    self.auto.scroll_feed(scroll_count=random.randint(2, 5))
                    summary["scrolls"] += 1
                    time.sleep(random.uniform(3.0, 8.0))
                    self.auto.navigate_to_home()

            except Exception as exc:
                logger.warning(
                    f"[{self.account_name}] RedGifs action '{action}' failed: {exc}"
                )
                try:
                    self.auto.navigate_to_home()
                except Exception:
                    break

            self._think_pause()

        elapsed = (time.monotonic() - start) / 60
        summary["duration_minutes"] = round(elapsed, 1)

        self._record_session(summary)

        logger.info(
            f"[{self.account_name}] RedGifs simulation complete: "
            f"{summary['duration_minutes']}min, "
            f"{summary['likes']} likes, "
            f"{summary['scrolls']} scrolls"
        )

        self.db.update_account_status(self.account_name, status="idle")
        return summary

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _pick_action(weights: dict[str, int]) -> str:
        actions = list(weights.keys())
        w = [weights[a] for a in actions]
        return random.choices(actions, weights=w, k=1)[0]

    def _think_pause(self) -> None:
        r = random.random()
        if r < 0.60:
            time.sleep(random.uniform(3.0, 8.0))
        elif r < 0.90:
            time.sleep(random.uniform(8.0, 20.0))
        else:
            time.sleep(random.uniform(20.0, 45.0))

    def _get_sessions_today(self) -> int:
        status = self.db.get_account_status(self.account_name)
        if not status:
            return 0
        today = date.today().isoformat()
        if getattr(status, "sim_date", None) != today:
            return 0
        return getattr(status, "sim_sessions_today", 0) or 0

    def _get_likes_today(self) -> int:
        status = self.db.get_account_status(self.account_name)
        if not status:
            return 0
        today = date.today().isoformat()
        if getattr(status, "sim_date", None) != today:
            return 0
        return getattr(status, "sim_likes_today", 0) or 0

    def _record_session(self, summary: dict) -> None:
        today = date.today().isoformat()
        status = self.db.get_account_status(self.account_name)

        prev_sessions = 0
        prev_likes = 0
        if status and getattr(status, "sim_date", None) == today:
            prev_sessions = getattr(status, "sim_sessions_today", 0) or 0
            prev_likes = getattr(status, "sim_likes_today", 0) or 0

        self.db.update_account_status(
            self.account_name,
            sim_date=today,
            sim_sessions_today=prev_sessions + 1,
            sim_likes_today=prev_likes + summary.get("likes", 0),
        )
