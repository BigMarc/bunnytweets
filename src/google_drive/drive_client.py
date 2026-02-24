from __future__ import annotations

import io
import json
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
    """Google Drive API wrapper using service-account credentials."""

    def __init__(self, credentials_file: str):
        creds = self._load_credentials(credentials_file)
        self.service = build("drive", "v3", credentials=creds, cache_discovery=False)

    @staticmethod
    def _load_credentials(credentials_file: str):
        """Load Google service-account credentials from a JSON key file."""
        creds_path = Path(credentials_file)

        with open(creds_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if data.get("type") == "service_account":
            return service_account.Credentials.from_service_account_file(
                credentials_file, scopes=SCOPES
            )

        raise ValueError(
            f"Expected a service-account JSON file (with '\"type\": \"service_account\"') "
            f"but got a different format in {credentials_file}. "
            f"If you downloaded an OAuth client ID JSON, that is the wrong type. "
            f"Go to Google Cloud Console > IAM & Admin > Service Accounts, "
            f"click your service account > Keys > Add Key > Create new key > JSON."
        )

    def _list_subfolder_ids(self, folder_id: str, page_size: int = 100, _depth: int = 10) -> list[str]:
        """Recursively discover all subfolder IDs under *folder_id*."""
        if _depth <= 0:
            logger.warning(f"Max folder depth reached scanning {folder_id}, stopping recursion")
            return []
        query = (
            f"'{folder_id}' in parents and trashed = false "
            f"and mimeType = 'application/vnd.google-apps.folder'"
        )
        subfolder_ids: list[str] = []
        page_token: str | None = None

        while True:
            kwargs: dict[str, Any] = dict(
                q=query,
                pageSize=page_size,
                fields="nextPageToken, files(id, name)",
                corpora="allDrives",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            if page_token:
                kwargs["pageToken"] = page_token

            results = self.service.files().list(**kwargs).execute()
            for f in results.get("files", []):
                subfolder_ids.append(f["id"])
                logger.debug(f"Discovered subfolder: {f['name']} ({f['id']})")
                # Recurse into this subfolder
                subfolder_ids.extend(self._list_subfolder_ids(f["id"], page_size, _depth - 1))

            page_token = results.get("nextPageToken")
            if not page_token:
                break

        return subfolder_ids

    def _list_files_in_single_folder(
        self, folder_id: str, page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """List non-folder files that are direct children of *folder_id*."""
        query = (
            f"'{folder_id}' in parents and trashed = false "
            f"and mimeType != 'application/vnd.google-apps.folder'"
        )
        files: list[dict[str, Any]] = []
        page_token: str | None = None

        while True:
            kwargs: dict[str, Any] = dict(
                q=query,
                pageSize=page_size,
                fields="nextPageToken, files(id, name, mimeType, createdTime, modifiedTime, size)",
                corpora="allDrives",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            if page_token:
                kwargs["pageToken"] = page_token

            results = self.service.files().list(**kwargs).execute()
            files.extend(results.get("files", []))
            page_token = results.get("nextPageToken")
            if not page_token:
                break

        return files

    def list_files(
        self,
        folder_id: str,
        file_types: list[str] | None = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """List files in a Google Drive folder **and all subfolders**, optionally filtered by extension.

        Supports both personal Drive and Shared Drives via
        ``corpora="allDrives"`` + ``supportsAllDrives`` / ``includeItemsFromAllDrives``.
        Paginates automatically so folders with >100 files are fully returned.
        Recursively scans subfolders so the content pool never runs dry.
        """
        # Collect all folder IDs: the root + every nested subfolder
        all_folder_ids = [folder_id] + self._list_subfolder_ids(folder_id, page_size)
        if len(all_folder_ids) > 1:
            logger.info(
                f"Drive scan: found {len(all_folder_ids)} folder(s) "
                f"(1 root + {len(all_folder_ids) - 1} subfolder(s))"
            )

        files: list[dict[str, Any]] = []
        for fid in all_folder_ids:
            files.extend(self._list_files_in_single_folder(fid, page_size))

        if file_types:
            allowed = {ft.lower().lstrip(".") for ft in file_types}
            files = [
                f
                for f in files
                if any(f["name"].lower().endswith(f".{ext}") for ext in allowed)
            ]

        return files

    def download_file(
        self, file_id: str, destination: Path, max_retries: int = 3,
        timeout: float = 300,
    ) -> Path:
        """Download a file from Google Drive to a local path.

        Args:
            timeout: Maximum total seconds for the download (default 300 = 5 min).

        Retries with exponential back-off on transient network / SSL errors.
        Raises TimeoutError if the download exceeds *timeout* seconds.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(1, max_retries + 1):
            try:
                request = self.service.files().get_media(
                    fileId=file_id, supportsAllDrives=True
                )
                start = time.monotonic()
                with open(destination, "wb") as fh:
                    downloader = MediaIoBaseDownload(fh, request)
                    done = False
                    while not done:
                        elapsed = time.monotonic() - start
                        if elapsed > timeout:
                            raise TimeoutError(
                                f"Download of {file_id} timed out after {elapsed:.0f}s "
                                f"(limit {timeout}s)"
                            )
                        status, done = downloader.next_chunk()
                        if status:
                            logger.debug(
                                f"Download {file_id}: {int(status.progress() * 100)}%"
                            )
                logger.info(f"Downloaded {file_id} -> {destination}")
                return destination
            except TimeoutError:
                raise
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
