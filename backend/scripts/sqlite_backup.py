"""Create and verify a consistent backup of the disposable development SQLite DB.

This is a development utility only. It is not a production backup strategy.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from pathlib import Path


def verify_database(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Database file does not exist: {path}")
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {result[0] if result else 'no result'}")
        fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise RuntimeError(f"SQLite foreign_key_check found {len(fk_errors)} violation(s)")
    finally:
        connection.close()


def backup_database(source: Path, destination: Path, overwrite: bool = False) -> None:
    # Do not follow a destination symlink: backup paths should never silently
    # replace a different file selected through a link.
    if destination.is_symlink():
        raise ValueError("Backup destination must not be a symbolic link")
    source = source.resolve()
    destination = destination.absolute()
    if source == destination.resolve():
        raise ValueError("Backup destination must differ from source database")
    if not source.is_file():
        raise FileNotFoundError(f"Source database does not exist: {source}")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Destination already exists (use --overwrite): {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with sqlite3.connect(source) as source_conn, sqlite3.connect(temporary) as target_conn:
            source_conn.backup(target_conn)
        verify_database(temporary)
        if overwrite:
            os.replace(temporary, destination)
        else:
            # A hard link publishes the verified temporary file only if the
            # destination is still absent, avoiding a check-then-replace race.
            # The temp file is in the same directory/filesystem by design.
            try:
                os.link(temporary, destination)
            except FileExistsError:
                raise FileExistsError(f"Destination already exists (use --overwrite): {destination}")
            temporary.unlink()
        verify_database(destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup_parser = subparsers.add_parser("backup", help="create a consistent SQLite backup")
    backup_parser.add_argument("destination", type=Path, help="backup file path")
    backup_parser.add_argument("--source", type=Path, help="source DB (defaults to SCHOOL_DEV_DB_PATH or app default)")
    backup_parser.add_argument("--overwrite", action="store_true", help="replace an existing destination")
    verify_parser = subparsers.add_parser("verify", help="check SQLite integrity and foreign keys")
    verify_parser.add_argument("database", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "verify":
            verify_database(args.database)
            print(f"OK: SQLite integrity and foreign-key checks passed: {args.database}")
            return 0
        source = args.source
        if source is None:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from app.services.student_store import database_path
            source = Path(database_path())
        backup_database(source, args.destination, args.overwrite)
        print(f"OK: verified SQLite backup created: {args.destination}")
        print("Reminder: this is a local development backup, not a production RPO/RTO solution.")
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
