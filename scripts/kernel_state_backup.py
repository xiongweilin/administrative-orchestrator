from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def backup(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Kernel state database does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as backup_db:
        source_db.backup(backup_db)
        _require_integrity(backup_db)


def restore(source_backup: Path, destination: Path) -> None:
    if not source_backup.is_file():
        raise FileNotFoundError(f"Kernel state backup does not exist: {source_backup}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".restore-tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        with sqlite3.connect(source_backup) as backup_db, sqlite3.connect(temporary) as restored_db:
            _require_integrity(backup_db)
            backup_db.backup(restored_db)
            _require_integrity(restored_db)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def verify(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    with sqlite3.connect(path) as db:
        _require_integrity(db)


def _require_integrity(db: sqlite3.Connection) -> None:
    row = db.execute("PRAGMA integrity_check").fetchone()
    if row is None or row[0] != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {row!r}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Online backup/restore for the single-writer Agent Kernel SQLite state store."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("source", type=Path)
    backup_parser.add_argument("destination", type=Path)
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("source", type=Path)
    restore_parser.add_argument("destination", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("path", type=Path)
    args = parser.parse_args()

    if args.command == "backup":
        backup(args.source, args.destination)
    elif args.command == "restore":
        restore(args.source, args.destination)
    else:
        verify(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
