from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import BackupConfig


DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


@dataclass(frozen=True)
class DriveItem:
    id: str
    name: str
    mime_type: str
    modified_time: str | None = None
    md5_checksum: str | None = None
    size: int | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "DriveItem":
        size = data.get("size")
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            mime_type=str(data["mimeType"]),
            modified_time=data.get("modifiedTime"),
            md5_checksum=data.get("md5Checksum"),
            size=int(size) if size is not None else None,
        )

    @property
    def is_folder(self) -> bool:
        return self.mime_type == GOOGLE_FOLDER_MIME_TYPE

    @property
    def is_google_workspace_file(self) -> bool:
        return self.mime_type.startswith("application/vnd.google-apps.") and not self.is_folder


class GoogleDriveClient:
    def __init__(self, service: Any, *, include_trashed: bool = False) -> None:
        self._service = service
        self._include_trashed = include_trashed

    def list_children(self, folder_id: str) -> list[DriveItem]:
        query_parts = [f"'{folder_id}' in parents"]
        if not self._include_trashed:
            query_parts.append("trashed = false")

        children: list[DriveItem] = []
        page_token = None
        while True:
            response = (
                self._service.files()
                .list(
                    q=" and ".join(query_parts),
                    spaces="drive",
                    fields=(
                        "nextPageToken, files("
                        "id, name, mimeType, modifiedTime, md5Checksum, size"
                        ")"
                    ),
                    pageSize=1000,
                    pageToken=page_token,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                )
                .execute()
            )
            children.extend(DriveItem.from_api(item) for item in response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return children

    def download_file(self, file_id: str, destination: Path) -> None:
        request = self._service.files().get_media(
            fileId=file_id,
            supportsAllDrives=True,
        )
        _download_request(request, destination)

    def export_file(self, file_id: str, export_mime_type: str, destination: Path) -> None:
        request = self._service.files().export_media(
            fileId=file_id,
            mimeType=export_mime_type,
        )
        _download_request(request, destination)


def build_drive_client(config: BackupConfig) -> GoogleDriveClient:
    service = build_drive_service(config)
    return GoogleDriveClient(service, include_trashed=config.include_trashed)


def build_drive_service(config: BackupConfig) -> Any:
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError("Install project dependencies before using Google Drive backup.") from exc

    credentials = _build_credentials(config)
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _build_credentials(config: BackupConfig) -> Any:
    if config.auth.service_account_file:
        from google.oauth2 import service_account

        return service_account.Credentials.from_service_account_file(
            str(config.auth.service_account_file),
            scopes=[DRIVE_READONLY_SCOPE],
        )

    return _build_oauth_credentials(
        client_secrets_file=config.auth.oauth_client_secrets_file,
        token_file=config.auth.oauth_token_file,
    )


def _build_oauth_credentials(client_secrets_file: Path | None, token_file: Path) -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    credentials = None
    if token_file.exists():
        credentials = Credentials.from_authorized_user_file(
            str(token_file),
            scopes=[DRIVE_READONLY_SCOPE],
        )

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        if not client_secrets_file:
            raise ValueError(
                "OAuth client secrets file is required when service_account_file is not set."
            )
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_secrets_file),
            scopes=[DRIVE_READONLY_SCOPE],
        )
        credentials = flow.run_local_server(port=0)

    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def _download_request(request: Any, destination: Path) -> None:
    try:
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError("Install project dependencies before downloading files.") from exc

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as file:
        downloader = MediaIoBaseDownload(file, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
