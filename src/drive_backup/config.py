from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_EXPORT_MIME_TYPES: dict[str, dict[str, str]] = {
    "application/vnd.google-apps.document": {
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "extension": ".docx",
    },
    "application/vnd.google-apps.spreadsheet": {
        "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "extension": ".xlsx",
    },
    "application/vnd.google-apps.presentation": {
        "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "extension": ".pptx",
    },
    "application/vnd.google-apps.drawing": {
        "mime_type": "image/png",
        "extension": ".png",
    },
}


@dataclass(frozen=True)
class ExportRule:
    mime_type: str
    extension: str


@dataclass(frozen=True)
class AuthConfig:
    service_account_file: Path | None = None
    oauth_client_secrets_file: Path | None = None
    oauth_token_file: Path = Path("~/.config/gdrive-folder-backup/token.json")


@dataclass(frozen=True)
class BackupConfig:
    folder_id: str
    destination: Path
    include_trashed: bool = False
    auth: AuthConfig = field(default_factory=AuthConfig)
    export_mime_types: dict[str, ExportRule] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.folder_id:
            raise ValueError("folder_id is required")
        if not self.destination:
            raise ValueError("destination is required")
        if not self.export_mime_types:
            object.__setattr__(
                self,
                "export_mime_types",
                {
                    source: ExportRule(**rule)
                    for source, rule in DEFAULT_EXPORT_MIME_TYPES.items()
                },
            )


def load_config(path: Path) -> BackupConfig:
    """Load backup configuration from YAML or JSON."""
    data = _read_mapping(path.expanduser())
    return config_from_mapping(data)


def config_from_mapping(data: dict[str, Any]) -> BackupConfig:
    folder_id = str(
        data.get("folder_id") or os.environ.get("BACKUP_DRIVE_FOLDER_ID") or ""
    )
    destination = Path(
        data.get("destination") or os.environ.get("BACKUP_DESTINATION") or ""
    ).expanduser()

    auth_data = data.get("auth") or {}
    service_account = (
        auth_data.get("service_account_file")
        or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    )
    client_secrets = auth_data.get("oauth_client_secrets_file") or os.environ.get(
        "GOOGLE_OAUTH_CLIENT_SECRETS"
    )
    token_file = auth_data.get("oauth_token_file") or os.environ.get(
        "GOOGLE_OAUTH_TOKEN_FILE",
        "~/.config/gdrive-folder-backup/token.json",
    )

    export_rules = {
        source_mime: ExportRule(
            mime_type=str(rule["mime_type"]),
            extension=_normalize_extension(str(rule["extension"])),
        )
        for source_mime, rule in (
            data.get("export_mime_types") or DEFAULT_EXPORT_MIME_TYPES
        ).items()
    }

    return BackupConfig(
        folder_id=folder_id,
        destination=destination,
        include_trashed=bool(data.get("include_trashed", False)),
        auth=AuthConfig(
            service_account_file=Path(service_account).expanduser()
            if service_account
            else None,
            oauth_client_secrets_file=Path(client_secrets).expanduser()
            if client_secrets
            else None,
            oauth_token_file=Path(token_file).expanduser(),
        ),
        export_mime_types=export_rules,
    )


def _read_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        if path.suffix.lower() == ".json":
            data = json.load(file)
        else:
            try:
                import yaml
            except ImportError as exc:  # pragma: no cover - depends on environment
                raise RuntimeError(
                    "PyYAML is required for YAML config files. Use JSON or install dependencies."
                ) from exc
            data = yaml.safe_load(file) or {}

    if not isinstance(data, dict):
        raise ValueError("config file must contain a mapping/object")
    return data


def _normalize_extension(extension: str) -> str:
    if not extension:
        return extension
    return extension if extension.startswith(".") else f".{extension}"
