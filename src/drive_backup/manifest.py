from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


MANIFEST_FILENAME = ".gdrive-backup-manifest.json"


@dataclass
class ManifestEntry:
    file_id: str
    relative_path: str
    mime_type: str
    modified_time: str | None
    md5_checksum: str | None
    size: int | None
    export_mime_type: str | None
    backed_up_at: str


class Manifest:
    def __init__(self, entries: dict[str, ManifestEntry] | None = None) -> None:
        self.entries = entries or {}

    @classmethod
    def load(cls, destination: Path) -> "Manifest":
        path = destination / MANIFEST_FILENAME
        if not path.exists():
            return cls()

        data = json.loads(path.read_text(encoding="utf-8"))
        entries = {
            file_id: ManifestEntry(**entry)
            for file_id, entry in data.get("files", {}).items()
        }
        return cls(entries)

    def save(self, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / MANIFEST_FILENAME
        payload = {
            "version": 1,
            "updated_at": utc_now(),
            "files": {
                file_id: asdict(entry)
                for file_id, entry in sorted(self.entries.items())
            },
        }
        temp_path = path.with_suffix(f"{path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(path)

    def mark_backed_up(
        self,
        *,
        file_id: str,
        relative_path: str,
        mime_type: str,
        modified_time: str | None,
        md5_checksum: str | None,
        size: int | None,
        export_mime_type: str | None,
    ) -> None:
        self.entries[file_id] = ManifestEntry(
            file_id=file_id,
            relative_path=relative_path,
            mime_type=mime_type,
            modified_time=modified_time,
            md5_checksum=md5_checksum,
            size=size,
            export_mime_type=export_mime_type,
            backed_up_at=utc_now(),
        )

    def remove_missing(self, present_file_ids: set[str]) -> list[ManifestEntry]:
        removed: list[ManifestEntry] = []
        for file_id in list(self.entries):
            if file_id not in present_file_ids:
                removed.append(self.entries.pop(file_id))
        return removed


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
