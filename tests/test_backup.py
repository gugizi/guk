from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from drive_backup.backup import BackupRunner, safe_path_component
from drive_backup.config import BackupConfig
from drive_backup.drive_client import GOOGLE_FOLDER_MIME_TYPE, DriveItem


DOC_MIME_TYPE = "application/vnd.google-apps.document"
PDF_MIME_TYPE = "application/pdf"


class FakeDriveClient:
    def __init__(self, children: dict[str, list[DriveItem]]) -> None:
        self.children = children
        self.downloaded: list[str] = []
        self.exported: list[tuple[str, str]] = []

    def list_children(self, folder_id: str) -> list[DriveItem]:
        return self.children.get(folder_id, [])

    def download_file(self, file_id: str, destination: Path) -> None:
        self.downloaded.append(file_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(f"download:{file_id}".encode("utf-8"))

    def export_file(self, file_id: str, export_mime_type: str, destination: Path) -> None:
        self.exported.append((file_id, export_mime_type))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(f"export:{file_id}:{export_mime_type}".encode("utf-8"))


class BackupRunnerTests(unittest.TestCase):
    def test_sanitizes_unsafe_path_components(self) -> None:
        self.assertEqual(safe_path_component("bad/name\\with\x00chars"), "bad_name_with_chars")
        self.assertEqual(safe_path_component("..", fallback="fallback"), "fallback")

    def test_backs_up_nested_files_and_exports_google_docs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            client = FakeDriveClient(
                {
                    "root": [
                        item("folder-1", "Reports", GOOGLE_FOLDER_MIME_TYPE),
                        item("file-1", "Budget", DOC_MIME_TYPE, modified_time="2026-01-01T00:00:00Z"),
                    ],
                    "folder-1": [
                        item(
                            "file-2",
                            "receipt.pdf",
                            PDF_MIME_TYPE,
                            md5_checksum="abc123",
                            modified_time="2026-01-02T00:00:00Z",
                            size=10,
                        )
                    ],
                }
            )

            summary = BackupRunner(config(destination), client).run()

            self.assertEqual(summary.folders_seen, 1)
            self.assertEqual(summary.files_seen, 2)
            self.assertEqual(summary.downloaded, 1)
            self.assertEqual(summary.exported, 1)
            self.assertTrue((destination / "Reports" / "receipt.pdf").exists())
            self.assertTrue((destination / "Budget.docx").exists())
            self.assertTrue((destination / ".gdrive-backup-manifest.json").exists())

    def test_skips_unchanged_files_on_second_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            children = {
                "root": [
                    item(
                        "file-1",
                        "receipt.pdf",
                        PDF_MIME_TYPE,
                        md5_checksum="abc123",
                        modified_time="2026-01-02T00:00:00Z",
                        size=10,
                    )
                ]
            }
            first_client = FakeDriveClient(children)
            BackupRunner(config(destination), first_client).run()

            second_client = FakeDriveClient(children)
            summary = BackupRunner(config(destination), second_client).run()

            self.assertEqual(summary.skipped_unchanged, 1)
            self.assertEqual(second_client.downloaded, [])

    def test_disambiguates_duplicate_file_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            client = FakeDriveClient(
                {
                    "root": [
                        item("abcdefgh123", "same.pdf", PDF_MIME_TYPE, md5_checksum="1"),
                        item("ijklmnop456", "same.pdf", PDF_MIME_TYPE, md5_checksum="2"),
                    ]
                }
            )

            BackupRunner(config(destination), client).run()

            self.assertTrue((destination / "same.pdf").exists())
            self.assertTrue((destination / "same [ijklmnop].pdf").exists())

    def test_prunes_files_removed_from_drive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            first_client = FakeDriveClient(
                {
                    "root": [
                        item("file-1", "old.pdf", PDF_MIME_TYPE, md5_checksum="abc123")
                    ]
                }
            )
            BackupRunner(config(destination), first_client).run()
            self.assertTrue((destination / "old.pdf").exists())

            second_client = FakeDriveClient({"root": []})
            summary = BackupRunner(config(destination), second_client).run(prune=True)

            self.assertEqual(summary.pruned, 1)
            self.assertFalse((destination / "old.pdf").exists())


def config(destination: Path) -> BackupConfig:
    return BackupConfig(folder_id="root", destination=destination)


def item(
    file_id: str,
    name: str,
    mime_type: str,
    *,
    modified_time: str | None = None,
    md5_checksum: str | None = None,
    size: int | None = None,
) -> DriveItem:
    return DriveItem(
        id=file_id,
        name=name,
        mime_type=mime_type,
        modified_time=modified_time,
        md5_checksum=md5_checksum,
        size=size,
    )


if __name__ == "__main__":
    unittest.main()
