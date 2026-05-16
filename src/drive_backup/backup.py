from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol

from .config import BackupConfig, ExportRule
from .drive_client import DriveItem
from .manifest import Manifest


class DriveClient(Protocol):
    def list_children(self, folder_id: str) -> list[DriveItem]:
        ...

    def download_file(self, file_id: str, destination: Path) -> None:
        ...

    def export_file(self, file_id: str, export_mime_type: str, destination: Path) -> None:
        ...


@dataclass
class BackupSummary:
    folders_seen: int = 0
    files_seen: int = 0
    downloaded: int = 0
    exported: int = 0
    skipped_unchanged: int = 0
    skipped_unsupported: int = 0
    pruned: int = 0
    warnings: list[str] = field(default_factory=list)


class BackupRunner:
    def __init__(self, config: BackupConfig, drive_client: DriveClient) -> None:
        self._config = config
        self._drive_client = drive_client

    def run(self, *, dry_run: bool = False, prune: bool = False) -> BackupSummary:
        destination = self._config.destination
        if not dry_run:
            destination.mkdir(parents=True, exist_ok=True)

        manifest = Manifest.load(destination)
        summary = BackupSummary()
        present_file_ids: set[str] = set()
        used_relative_paths: set[PurePosixPath] = set()

        self._walk_folder(
            folder_id=self._config.folder_id,
            relative_dir=PurePosixPath("."),
            manifest=manifest,
            summary=summary,
            present_file_ids=present_file_ids,
            used_relative_paths=used_relative_paths,
            dry_run=dry_run,
        )

        if prune:
            removed_entries = manifest.remove_missing(present_file_ids)
            for entry in removed_entries:
                target = _destination_path(destination, PurePosixPath(entry.relative_path))
                if target.exists() and not dry_run:
                    target.unlink()
                summary.pruned += 1

        if not dry_run:
            manifest.save(destination)
        return summary

    def _walk_folder(
        self,
        *,
        folder_id: str,
        relative_dir: PurePosixPath,
        manifest: Manifest,
        summary: BackupSummary,
        present_file_ids: set[str],
        used_relative_paths: set[PurePosixPath],
        dry_run: bool,
    ) -> None:
        for item in sorted(
            self._drive_client.list_children(folder_id),
            key=lambda child: (not child.is_folder, child.name.casefold(), child.id),
        ):
            safe_name = safe_path_component(item.name, fallback=f"drive-{item.id[:8]}")

            if item.is_folder:
                summary.folders_seen += 1
                child_dir = _unique_relative_path(
                    relative_dir / safe_name,
                    item.id,
                    used_relative_paths,
                )
                self._walk_folder(
                    folder_id=item.id,
                    relative_dir=child_dir,
                    manifest=manifest,
                    summary=summary,
                    present_file_ids=present_file_ids,
                    used_relative_paths=used_relative_paths,
                    dry_run=dry_run,
                )
                continue

            summary.files_seen += 1
            present_file_ids.add(item.id)
            export_rule = self._config.export_mime_types.get(item.mime_type)
            if item.is_google_workspace_file and not export_rule:
                summary.skipped_unsupported += 1
                summary.warnings.append(
                    f"Skipped {item.name!r}: no export rule for {item.mime_type}"
                )
                continue

            relative_path = _unique_relative_path(
                relative_dir / _name_with_export_extension(safe_name, export_rule),
                item.id,
                used_relative_paths,
            )
            target = _destination_path(self._config.destination, relative_path)
            export_mime_type = export_rule.mime_type if export_rule else None

            if not _needs_backup(
                manifest=manifest,
                item=item,
                relative_path=relative_path,
                target=target,
                export_mime_type=export_mime_type,
            ):
                summary.skipped_unchanged += 1
                continue

            if not dry_run:
                temp_target = target.with_name(f".{target.name}.tmp-{item.id[:12]}")
                if export_rule:
                    self._drive_client.export_file(item.id, export_rule.mime_type, temp_target)
                else:
                    self._drive_client.download_file(item.id, temp_target)
                temp_target.replace(target)

                manifest.mark_backed_up(
                    file_id=item.id,
                    relative_path=str(relative_path),
                    mime_type=item.mime_type,
                    modified_time=item.modified_time,
                    md5_checksum=item.md5_checksum,
                    size=item.size,
                    export_mime_type=export_mime_type,
                )

            if export_rule:
                summary.exported += 1
            else:
                summary.downloaded += 1


def safe_path_component(name: str, *, fallback: str = "unnamed") -> str:
    cleaned = re.sub(r"[/\\\x00-\x1f\x7f]+", "_", name).strip()
    if cleaned in {"", ".", ".."}:
        return fallback
    return cleaned


def _name_with_export_extension(name: str, export_rule: ExportRule | None) -> str:
    if not export_rule:
        return name
    if name.casefold().endswith(export_rule.extension.casefold()):
        return name
    return f"{name}{export_rule.extension}"


def _unique_relative_path(
    desired: PurePosixPath,
    file_id: str,
    used_relative_paths: set[PurePosixPath],
) -> PurePosixPath:
    if desired not in used_relative_paths:
        used_relative_paths.add(desired)
        return desired

    suffix = file_id[:8]
    stem = desired.stem
    suffix_part = desired.suffix
    candidate = desired.with_name(f"{stem} [{suffix}]{suffix_part}")
    counter = 2
    while candidate in used_relative_paths:
        candidate = desired.with_name(f"{stem} [{suffix}-{counter}]{suffix_part}")
        counter += 1

    used_relative_paths.add(candidate)
    return candidate


def _needs_backup(
    *,
    manifest: Manifest,
    item: DriveItem,
    relative_path: PurePosixPath,
    target: Path,
    export_mime_type: str | None,
) -> bool:
    entry = manifest.entries.get(item.id)
    if not target.exists() or not entry:
        return True

    if entry.relative_path != str(relative_path):
        return True
    if entry.mime_type != item.mime_type:
        return True
    if entry.export_mime_type != export_mime_type:
        return True

    if item.md5_checksum:
        return entry.md5_checksum != item.md5_checksum

    return entry.modified_time != item.modified_time or entry.size != item.size


def _destination_path(destination: Path, relative_path: PurePosixPath) -> Path:
    root = destination.resolve(strict=False)
    target = (root / Path(*relative_path.parts)).resolve(strict=False)
    if target != root and root not in target.parents:
        raise ValueError(f"backup path escapes destination: {relative_path}")
    return target
