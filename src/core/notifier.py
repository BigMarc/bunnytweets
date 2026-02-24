"""Discord webhook notifier for troubleshooting alerts."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

import requests
from loguru import logger


class DiscordNotifier:
    """Sends troubleshooting alerts to a Discord webhook (optionally into a thread)."""

    def __init__(self, webhook_url: str, thread_id: str | None = None, enabled: bool = True):
        self.webhook_url = webhook_url
        self.thread_id = thread_id
        self.enabled = enabled

    @classmethod
    def from_config(cls, discord_cfg: dict) -> "DiscordNotifier":
        return cls(
            webhook_url=discord_cfg.get("webhook_url", ""),
            thread_id=discord_cfg.get("thread_id"),
            enabled=discord_cfg.get("enabled", True),
        )

    def send(self, title: str, description: str, color: int = 0xFF4444,
             fields: list[dict[str, Any]] | None = None) -> None:
        """Send an embed message. Non-blocking (fires in a background thread)."""
        if not self.enabled or not self.webhook_url:
            return
        threading.Thread(
            target=self._send_sync,
            args=(title, description, color, fields),
            daemon=True,
        ).start()

    def _send_sync(self, title: str, description: str, color: int,
                   fields: list[dict[str, Any]] | None) -> None:
        try:
            embed: dict[str, Any] = {
                "title": title,
                "description": description,
                "color": color,
                "timestamp": datetime.utcnow().isoformat(),
                "footer": {"text": "BunnyTweets Automation"},
            }
            if fields:
                embed["fields"] = fields

            payload: dict[str, Any] = {"embeds": [embed]}

            url = self.webhook_url
            if self.thread_id:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}thread_id={self.thread_id}"

            resp = requests.post(url, json=payload, timeout=10)
            if not (200 <= resp.status_code < 300):
                logger.warning(f"Discord webhook returned {resp.status_code}: {resp.text[:200]}")
        except Exception as exc:
            logger.warning(f"Discord notification failed: {exc}")

    # ----- Convenience methods -----
    def alert_browser_failed(self, account_name: str, error: str) -> None:
        self.send(
            title="Browser Start Failed",
            description=f"Could not start browser for **{account_name}**.",
            fields=[{"name": "Error", "value": f"```{error[:1000]}```", "inline": False}],
        )

    def alert_not_logged_in(self, account_name: str) -> None:
        self.send(
            title="Account Not Logged In",
            description=f"**{account_name}** is not logged in to Twitter. Manual login required.",
            color=0xFFA500,
        )

    def alert_health_check_failed(self, account_name: str, error: str) -> None:
        self.send(
            title="Health Check Failed",
            description=f"Browser for **{account_name}** is unresponsive.",
            fields=[{"name": "Error", "value": f"```{error[:1000]}```", "inline": False}],
        )

    def alert_post_failed(self, account_name: str, error: str) -> None:
        self.send(
            title="Posting Failed",
            description=f"**{account_name}** failed to post a tweet.",
            fields=[{"name": "Error", "value": f"```{error[:1000]}```", "inline": False}],
        )

    def alert_drive_unreachable(self, account_name: str, error: str) -> None:
        self.send(
            title="Google Drive Unreachable",
            description=f"**{account_name}** cannot reach Google Drive.",
            color=0xFFA500,
            fields=[{"name": "Error", "value": f"```{error[:1000]}```", "inline": False}],
        )

    def alert_retweet_failed(self, account_name: str, error: str) -> None:
        self.send(
            title="Retweet Failed",
            description=f"**{account_name}** failed to retweet.",
            fields=[{"name": "Error", "value": f"```{error[:1000]}```", "inline": False}],
        )

    def alert_proxy_error(self, account_name: str, error: str) -> None:
        self.send(
            title="Proxy / Connection Error",
            description=f"**{account_name}** has a proxy or network issue.",
            color=0xFF6600,
            fields=[{"name": "Error", "value": f"```{error[:1000]}```", "inline": False}],
        )

    def alert_generic(self, account_name: str, title: str, error: str) -> None:
        self.send(
            title=title,
            description=f"Account: **{account_name}**",
            fields=[{"name": "Details", "value": f"```{error[:1000]}```", "inline": False}],
        )
