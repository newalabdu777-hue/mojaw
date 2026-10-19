from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.sqlite_backup import backup_database, verify_database


class SQLiteBackupTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.source = self.root / "source.sqlite3"
        with sqlite3.connect(self.source) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
            conn.execute("CREATE TABLE children (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parents(id))")
            conn.execute("INSERT INTO parents(id) VALUES (1)")
            conn.execute("INSERT INTO children(id, parent_id) VALUES (7, 1)")

    def tearDown(self):
        self.tempdir.cleanup()

    def test_backup_is_integrity_checked_and_contains_data(self):
        destination = self.root / "backups" / "copy.sqlite3"
        backup_database(self.source, destination)
        verify_database(destination)
        with sqlite3.connect(destination) as conn:
            self.assertEqual(conn.execute("SELECT parent_id FROM children WHERE id=7").fetchone(), (1,))

    def test_existing_destination_is_not_overwritten_by_default(self):
        destination = self.root / "copy.sqlite3"
        destination.write_bytes(b"keep this file")
        with self.assertRaises(FileExistsError):
            backup_database(self.source, destination)
        self.assertEqual(destination.read_bytes(), b"keep this file")

    def test_existing_destination_is_replaced_only_with_explicit_overwrite(self):
        destination = self.root / "copy.sqlite3"
        destination.write_bytes(b"old backup")
        backup_database(self.source, destination, overwrite=True)
        verify_database(destination)
        with sqlite3.connect(destination) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM parents").fetchone(), (1,))

    def test_verify_rejects_foreign_key_violations(self):
        broken = self.root / "fk-broken.sqlite3"
        with sqlite3.connect(broken) as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
            conn.execute("CREATE TABLE children (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parents(id))")
            conn.execute("INSERT INTO children(id, parent_id) VALUES (1, 404)")
        with self.assertRaisesRegex(RuntimeError, "foreign_key_check"):
            verify_database(broken)

    def test_backup_is_a_snapshot_not_a_live_link_to_source(self):
        destination = self.root / "copy.sqlite3"
        backup_database(self.source, destination)
        with sqlite3.connect(self.source) as conn:
            conn.execute("INSERT INTO parents(id) VALUES (2)")
        with sqlite3.connect(destination) as conn:
            ids = [row[0] for row in conn.execute("SELECT id FROM parents ORDER BY id")]
        self.assertEqual(ids, [1])

    def test_destination_symlink_is_rejected_without_touching_target(self):
        target = self.root / "important.bin"
        target.write_bytes(b"preserve me")
        destination = self.root / "backup-link.sqlite3"
        try:
            destination.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("Symbolic links are unavailable on this platform")
        with self.assertRaises(ValueError):
            backup_database(self.source, destination, overwrite=True)
        self.assertEqual(target.read_bytes(), b"preserve me")

    def test_corrupt_database_is_rejected_by_verify(self):
        corrupt = self.root / "corrupt.sqlite3"
        corrupt.write_bytes(b"not a sqlite database")
        with self.assertRaises(sqlite3.DatabaseError):
            verify_database(corrupt)

    def test_source_and_destination_must_differ(self):
        with self.assertRaises(ValueError):
            backup_database(self.source, self.source, overwrite=True)

    def test_verify_rejects_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            verify_database(self.root / "missing.sqlite3")


if __name__ == "__main__":
    unittest.main()
