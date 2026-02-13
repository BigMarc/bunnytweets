"""Abstract base classes defining the platform interface.

All platform implementations (Twitter, Threads, etc.) must implement
these ABCs so the scheduler, queue, and dashboard remain platform-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class PlatformAutomation(ABC):
    """Base class for low-level browser automation on a social platform."""

    @abstractmethod
    def is_logged_in(self) -> bool:
        """Check if the current browser session is authenticated."""

    @abstractmethod
    def navigate_to_home(self) -> None:
        """Navigate to the platform's home/feed page."""

    @abstractmethod
    def navigate_to_profile(self, username: str) -> None:
        """Navigate to a user's profile page."""

    @abstractmethod
    def get_current_url(self) -> str:
        """Get the current page URL."""


class Poster(ABC):
    """Base class for creating posts on a platform."""

    @abstractmethod
    def compose_post(self, text: str, media_paths: list[Path] | None = None) -> str | None:
        """Create a new post. Returns the post URL if available, else None."""

    @abstractmethod
    def compose_thread(self, posts: list[str]) -> str | None:
        """Create a multi-post thread. Returns URL of first post if available."""


class Reposter(ABC):
    """Base class for reposting/retweeting content."""

    @abstractmethod
    def repost(self, post_url: str) -> bool:
        """Repost/retweet a post. Returns True on success."""

    @abstractmethod
    def quote_post(self, post_url: str, text: str) -> str | None:
        """Quote a post with added text. Returns new post URL if available."""


class Replier(ABC):
    """Base class for replying to posts."""

    @abstractmethod
    def reply_to_post(self, post_url: str, text: str) -> bool:
        """Reply to a specific post. Returns True on success."""


class HumanSimulatorBase(ABC):
    """Base class for human-like browsing simulation."""

    @abstractmethod
    def simulate_session(self) -> dict:
        """Run a human-like browsing session. Returns summary dict."""

    @abstractmethod
    def scroll_feed(self, duration_seconds: int) -> None:
        """Scroll the feed for a specified duration with human-like behavior."""

    @abstractmethod
    def like_post_on_page(self) -> bool:
        """Like a random visible post on the current page."""

    @abstractmethod
    def type_like_human(self, element, text: str) -> None:
        """Type text character by character with random delays."""
