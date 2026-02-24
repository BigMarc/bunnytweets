"""Human-like browsing behaviour: scroll feed, like random posts, browse threads.

Each session runs for a configurable duration (30-60 min by default) and
performs a randomised mix of actions with variable delays to avoid detection.
Rate limits are enforced per-account per-day.
"""

from __future__ import annotations

import random
import time
from datetime import datetime, date

from loguru import logger

from src.core.database import Database
from src.twitter.automation import TwitterAutomation

# Action weights determine how often each action is chosen relative to others.
# Higher weight = more frequent.  Adjust via config.
DEFAULT_ACTION_WEIGHTS = {
    "scroll": 50,       # Just scroll the feed
    "like": 20,         # Like a tweet
    "open_thread": 15,  # Click into a thread & browse comments
    "explore": 10,      # Visit the Explore page
    "notifications": 5, # Check notifications briefly
}


class HumanSimulator:
    """Simulates natural browsing behaviour for a single Twitter account."""

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

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def run_session(self) -> dict:
        """Run a full human-simulation session.

        Returns a summary dict with counts of each action performed.
        """
        sim_cfg = self.config.get("human_simulation", {})
        if not sim_cfg.get("enabled", False):
            logger.info(
                f"[{self.account_name}] Human simulation is not enabled for this account — "
                "enable it in account settings under 'Human Simulation'"
            )
            return {}

        # Session duration (minutes)
        duration_min = sim_cfg.get("session_duration_min", 30)
        duration_max = sim_cfg.get("session_duration_max", 60)
        session_minutes = random.randint(duration_min, duration_max)

        # Daily limits
        daily_likes_limit = sim_cfg.get("daily_likes_limit", 30)
        daily_sessions_limit = sim_cfg.get("daily_sessions_limit", 2)

        # Check daily session count
        sessions_today = self._get_sessions_today()
        if sessions_today >= daily_sessions_limit:
            logger.info(
                f"[{self.account_name}] Daily session limit reached "
                f"({sessions_today}/{daily_sessions_limit}), skipping"
            )
            return {}

        # Check daily like count
        likes_today = self._get_likes_today()
        likes_remaining = max(0, daily_likes_limit - likes_today)

        # Action weights (configurable)
        weights = dict(DEFAULT_ACTION_WEIGHTS)
        custom_weights = sim_cfg.get("action_weights", {})
        weights.update(custom_weights)

        # If we've used all our likes, remove like from the pool
        if likes_remaining <= 0:
            weights.pop("like", None)

        logger.info(
            f"[{self.account_name}] Starting human simulation session "
            f"(~{session_minutes} min, {likes_remaining} likes remaining)"
        )

        self.db.update_account_status(
            self.account_name, status="browsing"
        )

        summary = {
            "scrolls": 0,
            "likes": 0,
            "threads_opened": 0,
            "explore_visits": 0,
            "notification_checks": 0,
            "duration_minutes": 0,
        }
        session_likes = 0

        start = time.monotonic()
        end_time = start + session_minutes * 60

        try:
            # Start on the home feed
            try:
                self.auto.navigate_home()
            except Exception as exc:
                logger.error(f"[{self.account_name}] Could not navigate home: {exc}")
                return summary

            while time.monotonic() < end_time:
                # Pick a random action based on weights
                action = self._pick_action(weights)

                try:
                    if action == "scroll":
                        count = random.randint(1, 4)
                        self.auto.scroll_feed(scroll_count=count)
                        summary["scrolls"] += count

                    elif action == "like":
                        if session_likes < likes_remaining:
                            if self.auto.like_tweet_on_page():
                                summary["likes"] += 1
                                session_likes += 1
                                if session_likes >= likes_remaining:
                                    weights.pop("like", None)
                        # Scroll a bit after liking
                        self.auto.scroll_feed(scroll_count=random.randint(1, 2))
                        summary["scrolls"] += 1

                    elif action == "open_thread":
                        if self.auto.open_random_thread():
                            summary["threads_opened"] += 1
                            # Browse comments in the thread
                            self.auto.browse_thread_comments()
                            # Maybe like something in the thread
                            if (
                                "like" in weights
                                and session_likes < likes_remaining
                                and random.random() < 0.25
                            ):
                                if self.auto.like_tweet_on_page():
                                    summary["likes"] += 1
                                    session_likes += 1
                            # Go back to the feed
                            self.auto.navigate_home()

                    elif action == "explore":
                        self.auto.navigate_explore()
                        summary["explore_visits"] += 1
                        # Scroll the explore page a bit
                        self.auto.scroll_feed(scroll_count=random.randint(2, 5))
                        summary["scrolls"] += 1
                        # Return home
                        time.sleep(random.uniform(3.0, 8.0))
                        self.auto.navigate_home()

                    elif action == "notifications":
                        self.auto.navigate_notifications()
                        summary["notification_checks"] += 1
                        time.sleep(random.uniform(5.0, 15.0))
                        # Scroll a bit
                        self.auto.scroll_feed(scroll_count=random.randint(1, 3))
                        self.auto.navigate_home()

                except Exception as exc:
                    logger.warning(
                        f"[{self.account_name}] Action '{action}' failed: {exc}"
                    )
                    # Try to recover by navigating home
                    try:
                        self.auto.navigate_home()
                    except Exception:
                        break

                # Variable pause between actions to simulate thinking / reading
                self._think_pause()

            elapsed = (time.monotonic() - start) / 60
            summary["duration_minutes"] = round(elapsed, 1)

            # Persist stats
            self._record_session(summary)

            logger.info(
                f"[{self.account_name}] Human simulation complete: "
                f"{summary['duration_minutes']}min, "
                f"{summary['likes']} likes, "
                f"{summary['scrolls']} scrolls, "
                f"{summary['threads_opened']} threads"
            )
            return summary

        finally:
            # GUARANTEE: never leave account stuck in "browsing"
            try:
                self.db.update_account_status(self.account_name, status="idle")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _pick_action(weights: dict[str, int]) -> str:
        """Weighted random choice of action."""
        actions = list(weights.keys())
        w = [weights[a] for a in actions]
        return random.choices(actions, weights=w, k=1)[0]

    def _think_pause(self) -> None:
        """Simulate a human thinking / reading pause between actions.

        The pause length varies widely to look natural:
        - Short pauses (skimming): 3-8 seconds (60% chance)
        - Medium pauses (reading): 8-20 seconds (30% chance)
        - Long pauses (distracted): 20-45 seconds (10% chance)
        """
        r = random.random()
        if r < 0.60:
            time.sleep(random.uniform(3.0, 8.0))
        elif r < 0.90:
            time.sleep(random.uniform(8.0, 20.0))
        else:
            time.sleep(random.uniform(20.0, 45.0))

    def _get_sessions_today(self) -> int:
        """Get the number of simulation sessions run today."""
        status = self.db.get_account_status(self.account_name)
        if not status:
            return 0
        today = date.today().isoformat()
        if getattr(status, "sim_date", None) != today:
            return 0
        return getattr(status, "sim_sessions_today", 0) or 0

    def _get_likes_today(self) -> int:
        """Get the number of likes performed today."""
        status = self.db.get_account_status(self.account_name)
        if not status:
            return 0
        today = date.today().isoformat()
        if getattr(status, "sim_date", None) != today:
            return 0
        return getattr(status, "sim_likes_today", 0) or 0

    def _record_session(self, summary: dict) -> None:
        """Persist session stats in the account status table."""
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
