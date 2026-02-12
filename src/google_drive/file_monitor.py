from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from src.core.database import Database
from src.google_drive.drive_client import DriveClient


class FileMonitor:
    """Monitors a Google Drive folder for new, unprocessed files."""

    def __init__(
        self,
        drive_client: DriveClient,
        database: Database,
        download_dir: str = "data/downloads",
    ):
        self.drive = drive_client
        self.db = database
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def list_all_files(
        self,
        account_name: str,
        folder_id: str,
        file_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return ALL files in the folder (for content rotation)."""
        all_files = self.drive.list_files(folder_id, file_types=file_types)
        logger.debug(
            f"[{account_name}] Drive folder has {len(all_files)} file(s)"
        )
        return all_files

    def check_for_new_files(
        self,
        account_name: str,
        folder_id: str,
        file_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return list of files in the folder that haven't been processed yet."""
        all_files = self.drive.list_files(folder_id, file_types=file_types)
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
