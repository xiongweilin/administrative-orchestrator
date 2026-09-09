from __future__ import annotations

import argparse
from pathlib import Path

from administrative_orchestrator.kernel_state_dr import (
    KernelStateRecoveryError,
    backup_kernel_state,
    restore_kernel_state,
    verify_kernel_state_backup,
)


def backup(source: Path, destination: Path) -> None:
    backup_kernel_state(source, destination)


def verify(path: Path) -> None:
    verify_kernel_state_backup(path)


def restore(source_backup: Path, destination: Path) -> None:
    restore_kernel_state(source_backup, destination)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Online backup, integrity verification, and restore for production Agent Kernel "
            "SQLite state."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("source", type=Path)
    backup_parser.add_argument("destination", type=Path)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("backup", type=Path)

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("backup", type=Path)
    restore_parser.add_argument("destination", type=Path)
    restore_parser.add_argument("--force", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "backup":
            digest = backup_kernel_state(args.source, args.destination)
            print(f"kernel state backup ready sha256={digest}")
        elif args.command == "verify":
            digest = verify_kernel_state_backup(args.backup)
            print(f"kernel state backup verified sha256={digest}")
        else:
            digest = restore_kernel_state(args.backup, args.destination, force=args.force)
            print(f"kernel state restored from verified backup sha256={digest}")
    except KernelStateRecoveryError as exc:
        raise SystemExit(f"kernel state DR failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
