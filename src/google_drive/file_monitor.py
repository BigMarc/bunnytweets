from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from loguru import logger

from src.core.database import Database
from src.google_drive.drive_client import DriveClient


class FileMonitor:
    """Monitors a Google Drive folder for new, unprocessed files.

    File listings are cached with a short TTL (default 5 minutes) to avoid
    redundant Drive API calls when multiple accounts share the same folder
    or when the bot restarts mid-cycle.
    """

    _DEFAULT_CACHE_TTL = 300  # 5 minutes

    def __init__(
        self,
        drive_client: DriveClient,
        database: Database,
        download_dir: str = "data/downloads",
        cache_ttl: int | None = None,
    ):
        self.drive = drive_client
        self.db = database
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._cache_ttl = cache_ttl if cache_ttl is not None else self._DEFAULT_CACHE_TTL
        # Cache: (folder_id, file_types_key) -> (timestamp, result_list)
        self._listing_cache: dict[tuple, tuple[float, list[dict[str, Any]]]] = {}

    def _cache_key(self, folder_id: str, file_types: list[str] | None) -> tuple:
        return (folder_id, tuple(sorted(file_types)) if file_types else ())

    def invalidate_cache(self, folder_id: str | None = None) -> None:
        """Clear the file listing cache (all folders or a specific one)."""
        if folder_id is None:
            self._listing_cache.clear()
            logger.debug("Drive file listing cache cleared (all folders)")
        else:
            keys = [k for k in self._listing_cache if k[0] == folder_id]
            for k in keys:
                del self._listing_cache[k]
            logger.debug(f"Drive file listing cache cleared for folder {folder_id}")

    def list_all_files(
        self,
        account_name: str,
        folder_id: str,
        file_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return ALL files in the folder (for content rotation).

        Results are cached for ``cache_ttl`` seconds to reduce Drive API
        usage when multiple accounts share the same folder.
        """
        key = self._cache_key(folder_id, file_types)
        now = time.monotonic()

        cached = self._listing_cache.get(key)
        if cached and (now - cached[0]) < self._cache_ttl:
            logger.debug(
                f"[{account_name}] Drive listing cache hit — "
                f"{len(cached[1])} file(s), {int(self._cache_ttl - (now - cached[0]))}s remaining"
            )
            return cached[1]

        all_files = self.drive.list_files(folder_id, file_types=file_types)
        self._listing_cache[key] = (now, all_files)
        logger.debug(
            f"[{account_name}] Drive folder has {len(all_files)} file(s) (cached for {self._cache_ttl}s)"
        )
        return all_files

    def check_for_new_files(
        self,
        account_name: str,
        folder_id: str,
        file_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return list of files in the folder that haven't been processed yet."""
        all_files = self.list_all_files(account_name, folder_id, file_types)
        new_files = []
        for f in all_files:
            if not self.db.is_file_processed(f["id"]):
                new_files.append(f)
        if new_files:
            logger.info(
                f"[{account_name}] Found {len(new_files)} new file(s) in Drive folder"
            )
        else:
            logger.debug(f"[{account_name}] No new files in Drive folder")
        return new_files

    def download_file(self, account_name: str, file_meta: dict) -> Path:
        """Download a file and return the local path."""
        account_dir = self.download_dir / account_name
        account_dir.mkdir(parents=True, exist_ok=True)
        dest = account_dir / file_meta["name"]
        self.drive.download_file(file_meta["id"], dest)
        return dest

    def mark_processed(
        self,
        account_name: str,
        file_meta: dict,
        tweet_id: str | None = None,
        status: str = "success",
    ) -> None:
        self.db.mark_file_processed(
            account_name=account_name,
            file_id=file_meta["id"],
            file_name=file_meta["name"],
            tweet_id=tweet_id,
            status=status,
        )
