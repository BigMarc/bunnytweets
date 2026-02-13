from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from loguru import logger

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Media MIME types we care about
SUPPORTED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "video/mp4",
    "video/quicktime",
    "text/plain",
}

EXTENSION_MAP = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "text/plain": ".txt",
}


class DriveClient:
    """Google Drive API wrapper using a service account."""

    def __init__(self, credentials_file: str):
        creds = service_account.Credentials.from_service_account_file(
            credentials_file, scopes=SCOPES
        )
        self.service = build("drive", "v3", credentials=creds, cache_discovery=False)

    def list_files(
        self,
        folder_id: str,
        file_types: list[str] | None = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """List files in a Google Drive folder, optionally filtered by extension.

        Supports both personal Drive and Shared Drives via
        ``corpora="allDrives"`` + ``supportsAllDrives`` / ``includeItemsFromAllDrives``.
        Paginates automatically so folders with >100 files are fully returned.
        """
        query = f"'{folder_id}' in parents and trashed = false"

        files: list[dict[str, Any]] = []
        page_token: str | None = None

        while True:
            request_kwargs: dict[str, Any] = dict(
                q=query,
                pageSize=page_size,
                fields="nextPageToken, files(id, name, mimeType, createdTime, modifiedTime, size)",
                corpora="allDrives",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            if page_token:
                request_kwargs["pageToken"] = page_token

            results = (
                self.service.files()
                .list(**request_kwargs)
                .execute()
            )
            files.extend(results.get("files", []))
            page_token = results.get("nextPageToken")
            if not page_token:
                break

        if file_types:
            allowed = {ft.lower().lstrip(".") for ft in file_types}
            files = [
                f
                for f in files
                if any(f["name"].lower().endswith(f".{ext}") for ext in allowed)
            ]

        return files

    def download_file(
        self, file_id: str, destination: Path, max_retries: int = 3
    ) -> Path:
        """Download a file from Google Drive to a local path.

        Retries with exponential back-off on transient network / SSL errors.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(1, max_retries + 1):
            try:
                request = self.service.files().get_media(
                    fileId=file_id, supportsAllDrives=True
                )
                with open(destination, "wb") as fh:
                    downloader = MediaIoBaseDownload(fh, request)
                    done = False
                    while not done:
                        status, done = downloader.next_chunk()
                        if status:
                            logger.debug(
                                f"Download {file_id}: {int(status.progress() * 100)}%"
                            )
                logger.info(f"Downloaded {file_id} -> {destination}")
                return destination
            except Exception as exc:
                if attempt < max_retries:
                    delay = 2 ** attempt
                    logger.warning(
                        f"Download {file_id} failed (attempt {attempt}/{max_retries}): "
                        f"{exc}. Retrying in {delay}s…"
                    )
                    time.sleep(delay)
                else:
                    raise

    def get_file_metadata(self, file_id: str) -> dict:
        return (
            self.service.files()
            .get(
                fileId=file_id,
                fields="id, name, mimeType, createdTime, modifiedTime, size",
                supportsAllDrives=True,
            )
            .execute()
        )
