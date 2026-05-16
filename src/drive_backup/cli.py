from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .backup import BackupRunner, BackupSummary
from .config import load_config
from .drive_client import build_drive_client


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        drive_client = build_drive_client(config)
        summary = BackupRunner(config, drive_client).run(
            dry_run=args.dry_run,
            prune=args.prune,
        )
    except Exception as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1

    _print_summary(summary, dry_run=args.dry_run)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gdrive-folder-backup",
        description="Back up a specific Google Drive folder to local storage.",
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to a YAML or JSON backup configuration file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List planned work without writing files or updating the manifest.",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Remove local files that were previously backed up but no longer exist in Drive.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _print_summary(summary: BackupSummary, *, dry_run: bool) -> None:
    prefix = "Dry run complete" if dry_run else "Backup complete"
    print(
        f"{prefix}: "
        f"{summary.files_seen} files, "
        f"{summary.folders_seen} folders, "
        f"{summary.downloaded} downloaded, "
        f"{summary.exported} exported, "
        f"{summary.skipped_unchanged} unchanged, "
        f"{summary.skipped_unsupported} unsupported, "
        f"{summary.pruned} pruned."
    )
    for warning in summary.warnings:
        print(f"Warning: {warning}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
