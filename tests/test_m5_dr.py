from __future__ import annotations

import sqlite3

from scripts.kernel_state_backup import backup, restore, verify


def test_kernel_state_online_backup_restore_round_trip(tmp_path):
    source = tmp_path / "kernel.db"
    backup_path = tmp_path / "backups" / "kernel.db"
    restored = tmp_path / "restored" / "kernel.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE recovery_fact (id TEXT PRIMARY KEY, status TEXT NOT NULL)")
        db.execute("INSERT INTO recovery_fact VALUES ('attempt:1', 'execution-unknown')")
        db.commit()

    backup(source, backup_path)
    with sqlite3.connect(source) as db:
        db.execute("UPDATE recovery_fact SET status = 'recovered-completed' WHERE id = 'attempt:1'")
        db.commit()

    restore(backup_path, restored)
    verify(restored)
    with sqlite3.connect(restored) as db:
        row = db.execute("SELECT status FROM recovery_fact WHERE id = 'attempt:1'").fetchone()

    assert row == ("execution-unknown",)
