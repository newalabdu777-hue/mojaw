"""Disposable SQLite store for local development only; not a production schema."""
from __future__ import annotations
import os
import sqlite3
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / ".dev_students.sqlite3"


def database_path() -> str:
    return os.environ.get("SCHOOL_DEV_DB_PATH", str(_DEFAULT_PATH))


def connect() -> sqlite3.Connection:
    db_path = database_path()
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _idempotency_request_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _idempotency_replay(conn: sqlite3.Connection, organization_id: str, operation: str, key: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT request_hash, response_json FROM prototype_finance_idempotency WHERE organization_id=? AND operation=? AND idempotency_key=?",
        (organization_id, operation, key),
    ).fetchone()
    if row is None:
        return None
    if row["request_hash"] != _idempotency_request_hash(payload):
        raise ValueError("Idempotency-Key was already used with a different request payload")
    return json.loads(row["response_json"])


def _save_idempotency(conn: sqlite3.Connection, organization_id: str, operation: str, key: str, payload: dict[str, Any], result: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO prototype_finance_idempotency (organization_id, operation, idempotency_key, request_hash, response_json) VALUES (?,?,?,?,?)",
        (organization_id, operation, key, _idempotency_request_hash(payload), json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)),
    )


def initialize() -> None:
    with db_session() as conn:
        # Development-only identity tables; production schema remains intentionally unapproved.
        from app.services.auth_service import ensure_auth_tables
        ensure_auth_tables(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_finance_idempotency (
                organization_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                PRIMARY KEY (organization_id, operation, idempotency_key)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_students (
                student_id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                branch_id TEXT NOT NULL,
                given_name TEXT NOT NULL,
                middle_name TEXT,
                family_name TEXT NOT NULL,
                date_of_birth TEXT,
                sex_at_registration TEXT NOT NULL,
                external_reference TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE (organization_id, student_id)
            )
        """)
        # Development-only forward migration for optimistic student sync versions.
        student_columns = {row["name"] for row in conn.execute("PRAGMA table_info(prototype_students)").fetchall()}
        if "version" not in student_columns:
            conn.execute("ALTER TABLE prototype_students ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_proto_students_org_branch ON prototype_students(organization_id, branch_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_proto_students_org_name ON prototype_students(organization_id, family_name, given_name)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_audit_events (
                event_id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                actor_id TEXT,
                source TEXT NOT NULL DEFAULT 'api-prototype',
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE (organization_id, event_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS ix_proto_audit_org_time ON prototype_audit_events(organization_id, created_at DESC, event_id)")
        conn.execute("CREATE TRIGGER IF NOT EXISTS tr_proto_audit_no_update BEFORE UPDATE ON prototype_audit_events BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END")
        conn.execute("CREATE TRIGGER IF NOT EXISTS tr_proto_audit_no_delete BEFORE DELETE ON prototype_audit_events BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_fee_bills (
                bill_id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                description TEXT NOT NULL,
                amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
                currency TEXT NOT NULL CHECK (length(currency) = 3),
                due_date TEXT,
                status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','void')),
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE (organization_id, bill_id),
                FOREIGN KEY (organization_id, student_id) REFERENCES prototype_students(organization_id, student_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS ix_proto_fee_bills_student ON prototype_fee_bills(organization_id, student_id, status)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_fee_payments (
                payment_id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                provisional_ref TEXT NOT NULL,
                amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
                currency TEXT NOT NULL CHECK (length(currency) = 3),
                payment_method TEXT NOT NULL,
                note TEXT,
                status TEXT NOT NULL DEFAULT 'pending_reconciliation' CHECK (status IN ('pending_reconciliation','reconciled','rejected')),
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                reconciled_at TEXT,
                UNIQUE (organization_id, payment_id),
                UNIQUE (organization_id, provisional_ref),
                FOREIGN KEY (organization_id, student_id) REFERENCES prototype_students(organization_id, student_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS ix_proto_fee_payments_student ON prototype_fee_payments(organization_id, student_id, status)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_fee_payment_allocations (
                organization_id TEXT NOT NULL,
                payment_id TEXT NOT NULL,
                bill_id TEXT NOT NULL,
                amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
                PRIMARY KEY (organization_id, payment_id, bill_id),
                FOREIGN KEY (organization_id, payment_id) REFERENCES prototype_fee_payments(organization_id, payment_id),
                FOREIGN KEY (organization_id, bill_id) REFERENCES prototype_fee_bills(organization_id, bill_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_student_account_entries (
                entry_id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                entry_type TEXT NOT NULL CHECK (entry_type IN ('fee_charge','payment_allocation','student_credit')),
                amount_minor INTEGER NOT NULL CHECK (amount_minor <> 0),
                currency TEXT NOT NULL CHECK (length(currency) = 3),
                bill_id TEXT,
                payment_id TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE (organization_id, entry_id),
                FOREIGN KEY (organization_id, student_id) REFERENCES prototype_students(organization_id, student_id),
                FOREIGN KEY (organization_id, bill_id) REFERENCES prototype_fee_bills(organization_id, bill_id),
                FOREIGN KEY (organization_id, payment_id) REFERENCES prototype_fee_payments(organization_id, payment_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS ix_proto_account_entries_student ON prototype_student_account_entries(organization_id, student_id, currency, created_at)")
        conn.execute("CREATE TRIGGER IF NOT EXISTS tr_proto_account_entries_no_update BEFORE UPDATE ON prototype_student_account_entries BEGIN SELECT RAISE(ABORT, 'student account journal is append-only'); END")
        conn.execute("CREATE TRIGGER IF NOT EXISTS tr_proto_account_entries_no_delete BEFORE DELETE ON prototype_student_account_entries BEGIN SELECT RAISE(ABORT, 'student account journal is append-only'); END")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_ledger_accounts (
                account_id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                account_type TEXT NOT NULL CHECK (account_type IN ('asset','liability','equity','revenue','expense')),
                currency TEXT NOT NULL CHECK (length(currency) = 3),
                status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE (organization_id, account_id),
                UNIQUE (organization_id, code)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_ledger_journals (
                journal_id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                description TEXT NOT NULL,
                currency TEXT NOT NULL CHECK (length(currency) = 3),
                status TEXT NOT NULL DEFAULT 'posted' CHECK (status = 'posted'),
                idempotency_key TEXT,
                request_hash TEXT,
                reversal_of_id TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE (organization_id, journal_id),
                FOREIGN KEY (organization_id, reversal_of_id) REFERENCES prototype_ledger_journals(organization_id, journal_id)
            )
        """)
        # Upgrade the disposable local prototype DB in place; this is not a production migration.
        journal_columns = {row[1] for row in conn.execute("PRAGMA table_info(prototype_ledger_journals)").fetchall()}
        if "idempotency_key" not in journal_columns:
            conn.execute("ALTER TABLE prototype_ledger_journals ADD COLUMN idempotency_key TEXT")
        if "request_hash" not in journal_columns:
            conn.execute("ALTER TABLE prototype_ledger_journals ADD COLUMN request_hash TEXT")
        if "reversal_of_id" not in journal_columns:
            conn.execute("ALTER TABLE prototype_ledger_journals ADD COLUMN reversal_of_id TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_proto_ledger_journal_reversal ON prototype_ledger_journals(organization_id, reversal_of_id) WHERE reversal_of_id IS NOT NULL")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_proto_ledger_journal_idempotency ON prototype_ledger_journals(organization_id, idempotency_key) WHERE idempotency_key IS NOT NULL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_ledger_lines (
                organization_id TEXT NOT NULL,
                journal_id TEXT NOT NULL,
                line_number INTEGER NOT NULL,
                account_id TEXT NOT NULL,
                debit_minor INTEGER NOT NULL DEFAULT 0 CHECK (debit_minor >= 0),
                credit_minor INTEGER NOT NULL DEFAULT 0 CHECK (credit_minor >= 0),
                PRIMARY KEY (organization_id, journal_id, line_number),
                CHECK ((debit_minor > 0 AND credit_minor = 0) OR (credit_minor > 0 AND debit_minor = 0)),
                FOREIGN KEY (organization_id, journal_id) REFERENCES prototype_ledger_journals(organization_id, journal_id),
                FOREIGN KEY (organization_id, account_id) REFERENCES prototype_ledger_accounts(organization_id, account_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS ix_proto_ledger_lines_account ON prototype_ledger_lines(organization_id, account_id, journal_id)")
        conn.execute("CREATE TRIGGER IF NOT EXISTS tr_proto_ledger_lines_no_update BEFORE UPDATE ON prototype_ledger_lines BEGIN SELECT RAISE(ABORT, 'posted general ledger is append-only'); END")
        conn.execute("CREATE TRIGGER IF NOT EXISTS tr_proto_ledger_lines_no_delete BEFORE DELETE ON prototype_ledger_lines BEGIN SELECT RAISE(ABORT, 'posted general ledger is append-only'); END")
        conn.execute("CREATE TRIGGER IF NOT EXISTS tr_proto_ledger_journals_no_update BEFORE UPDATE ON prototype_ledger_journals BEGIN SELECT RAISE(ABORT, 'posted general ledger is append-only'); END")
        conn.execute("CREATE TRIGGER IF NOT EXISTS tr_proto_ledger_journals_no_delete BEFORE DELETE ON prototype_ledger_journals BEGIN SELECT RAISE(ABORT, 'posted general ledger is append-only'); END")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_guardians (
                guardian_id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                given_name TEXT NOT NULL,
                family_name TEXT NOT NULL,
                phone TEXT,
                email TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE (organization_id, guardian_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_student_guardians (
                organization_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                guardian_id TEXT NOT NULL,
                relationship TEXT NOT NULL,
                is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0,1)),
                portal_access INTEGER NOT NULL DEFAULT 0 CHECK (portal_access IN (0,1)),
                PRIMARY KEY (organization_id, student_id, guardian_id),
                FOREIGN KEY (organization_id, student_id) REFERENCES prototype_students(organization_id, student_id) ON DELETE CASCADE,
                FOREIGN KEY (organization_id, guardian_id) REFERENCES prototype_guardians(organization_id, guardian_id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS ix_proto_guardians_student ON prototype_student_guardians(organization_id, student_id)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_attendance (
                attendance_id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                branch_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                attendance_date TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('present','absent','late','excused')),
                note TEXT,
                version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE (organization_id, student_id, attendance_date),
                UNIQUE (organization_id, attendance_id),
                FOREIGN KEY (organization_id, student_id) REFERENCES prototype_students(organization_id, student_id)
            )
        """)
        # Development-only forward migration for existing SQLite files.
        attendance_columns = {row["name"] for row in conn.execute("PRAGMA table_info(prototype_attendance)").fetchall()}
        if "version" not in attendance_columns:
            conn.execute("ALTER TABLE prototype_attendance ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_proto_attendance_org_date_branch ON prototype_attendance(organization_id, attendance_date, branch_id)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_assessments (
                assessment_id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                branch_id TEXT NOT NULL,
                section_id TEXT,
                subject TEXT NOT NULL,
                title TEXT NOT NULL,
                term TEXT NOT NULL,
                assessment_date TEXT,
                max_score TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published')),
                published_at TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE (organization_id, assessment_id)
            )
        """)
        # Local prototype compatibility only; production schema changes wait for approval.
        assessment_columns = {row["name"] for row in conn.execute("PRAGMA table_info(prototype_assessments)").fetchall()}
        if "section_id" not in assessment_columns:
            conn.execute("ALTER TABLE prototype_assessments ADD COLUMN section_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_proto_assessments_org_branch ON prototype_assessments(organization_id, branch_id, status)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_assessment_results (
                result_id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                assessment_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                score TEXT NOT NULL,
                comment TEXT,
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE (organization_id, assessment_id, student_id),
                FOREIGN KEY (organization_id, assessment_id) REFERENCES prototype_assessments(organization_id, assessment_id) ON DELETE CASCADE,
                FOREIGN KEY (organization_id, student_id) REFERENCES prototype_students(organization_id, student_id)
            )
        """)
        result_columns = {row["name"] for row in conn.execute("PRAGMA table_info(prototype_assessment_results)").fetchall()}
        if "version" not in result_columns:
            conn.execute("ALTER TABLE prototype_assessment_results ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_proto_results_org_assessment ON prototype_assessment_results(organization_id, assessment_id)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_assessment_result_history (
                history_id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                assessment_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                change_type TEXT NOT NULL CHECK (change_type IN ('created','updated')),
                previous_score TEXT,
                previous_comment TEXT,
                new_score TEXT NOT NULL,
                new_comment TEXT,
                changed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                FOREIGN KEY (organization_id, assessment_id) REFERENCES prototype_assessments(organization_id, assessment_id) ON DELETE CASCADE,
                FOREIGN KEY (organization_id, student_id) REFERENCES prototype_students(organization_id, student_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS ix_proto_result_history_org_assessment_student ON prototype_assessment_result_history(organization_id, assessment_id, student_id, changed_at)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_academic_years (
                year_id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','closed')),
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE (organization_id, year_id),
                UNIQUE (organization_id, name),
                CHECK (start_date <= end_date)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_class_levels (
                level_id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                name TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0 CHECK (sort_order >= 0),
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE (organization_id, level_id),
                UNIQUE (organization_id, name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_sections (
                section_id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                branch_id TEXT NOT NULL,
                year_id TEXT NOT NULL,
                level_id TEXT NOT NULL,
                name TEXT NOT NULL,
                capacity INTEGER CHECK (capacity IS NULL OR capacity > 0),
                status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE (organization_id, section_id),
                UNIQUE (organization_id, branch_id, year_id, level_id, name),
                FOREIGN KEY (organization_id, year_id) REFERENCES prototype_academic_years(organization_id, year_id),
                FOREIGN KEY (organization_id, level_id) REFERENCES prototype_class_levels(organization_id, level_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS ix_proto_sections_org_branch_year ON prototype_sections(organization_id, branch_id, year_id, status)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_enrollments (
                enrollment_id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                section_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','completed','withdrawn')),
                enrolled_on TEXT NOT NULL,
                ended_on TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE (organization_id, enrollment_id),
                FOREIGN KEY (organization_id, student_id) REFERENCES prototype_students(organization_id, student_id),
                FOREIGN KEY (organization_id, section_id) REFERENCES prototype_sections(organization_id, section_id),
                CHECK (ended_on IS NULL OR enrolled_on <= ended_on)
            )
        """)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_proto_enrollment_one_active_student ON prototype_enrollments(organization_id, student_id) WHERE status = 'active'")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_proto_enrollments_org_section ON prototype_enrollments(organization_id, section_id, status)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prototype_attendance_changes (
                change_id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                attendance_id TEXT NOT NULL,
                old_status TEXT NOT NULL,
                new_status TEXT NOT NULL,
                reason TEXT NOT NULL,
                changed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                FOREIGN KEY (organization_id, attendance_id) REFERENCES prototype_attendance(organization_id, attendance_id)
            )
        """)


def create_assessment(payload: dict[str, Any]) -> dict[str, Any]:
    import uuid
    assessment = {**payload, "assessment_id": str(uuid.uuid4())}
    with db_session() as conn:
        section_id = assessment.get("section_id")
        if section_id:
            section = conn.execute(
                "SELECT branch_id, status FROM prototype_sections WHERE organization_id = ? AND section_id = ?",
                (assessment["organization_id"], section_id),
            ).fetchone()
            if not section:
                raise LookupError("section")
            if section["status"] != "active":
                raise ValueError("Cannot create an assessment for an archived section")
            if section["branch_id"] != assessment["branch_id"]:
                raise ValueError("Assessment branch must match its section branch")
        conn.execute(
            "INSERT INTO prototype_assessments (assessment_id, organization_id, branch_id, section_id, subject, title, term, assessment_date, max_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (assessment["assessment_id"], assessment["organization_id"], assessment["branch_id"], section_id, assessment["subject"], assessment["title"], assessment["term"], assessment.get("assessment_date"), str(assessment["max_score"])),
        )
    return get_assessment(assessment["organization_id"], assessment["assessment_id"]) or assessment


def get_assessment(organization_id: str, assessment_id: str) -> dict[str, Any] | None:
    with db_session() as conn:
        row = conn.execute("SELECT * FROM prototype_assessments WHERE organization_id = ? AND assessment_id = ?", (organization_id, assessment_id)).fetchone()
    return dict(row) if row else None


def list_assessments(organization_id: str, branch_id: str | None = None) -> list[dict[str, Any]]:
    where = "organization_id = ?"
    args: list[Any] = [organization_id]
    if branch_id:
        where += " AND branch_id = ?"
        args.append(branch_id)
    with db_session() as conn:
        rows = conn.execute(f"SELECT * FROM prototype_assessments WHERE {where} ORDER BY created_at DESC", args).fetchall()
    return [dict(row) for row in rows]


def save_assessment_result(organization_id: str, assessment_id: str, student_id: str, score: str, comment: str | None) -> dict[str, Any] | None:
    import uuid
    with db_session() as conn:
        assessment = conn.execute("SELECT status, max_score, section_id FROM prototype_assessments WHERE organization_id = ? AND assessment_id = ?", (organization_id, assessment_id)).fetchone()
        if not assessment:
            return None
        if assessment["status"] != "draft":
            raise PermissionError("Published assessment results are immutable")
        student = conn.execute("SELECT 1 FROM prototype_students WHERE organization_id = ? AND student_id = ?", (organization_id, student_id)).fetchone()
        if not student:
            raise LookupError(student_id)
        if assessment["section_id"]:
            enrollment = conn.execute(
                "SELECT 1 FROM prototype_enrollments WHERE organization_id = ? AND section_id = ? AND student_id = ? AND status = 'active'",
                (organization_id, assessment["section_id"], student_id),
            ).fetchone()
            if not enrollment:
                raise ValueError("Student must have an active enrollment in the assessment section")
        from decimal import Decimal
        if Decimal(score) > Decimal(assessment["max_score"]):
            raise ValueError("Score cannot exceed assessment max_score")
        existing = conn.execute("SELECT result_id, score, comment, version FROM prototype_assessment_results WHERE organization_id = ? AND assessment_id = ? AND student_id = ?", (organization_id, assessment_id, student_id)).fetchone()
        history_id = str(uuid.uuid4())
        if existing:
            conn.execute("UPDATE prototype_assessment_results SET score = ?, comment = ?, version = version + 1, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE organization_id = ? AND assessment_id = ? AND student_id = ?", (score, comment, organization_id, assessment_id, student_id))
            result_id = existing["result_id"]
            change_type = "updated"
            previous_score = existing["score"]
            previous_comment = existing["comment"]
        else:
            result_id = str(uuid.uuid4())
            conn.execute("INSERT INTO prototype_assessment_results (result_id, organization_id, assessment_id, student_id, score, comment) VALUES (?, ?, ?, ?, ?, ?)", (result_id, organization_id, assessment_id, student_id, score, comment))
            change_type = "created"
            previous_score = None
            previous_comment = None
        conn.execute(
            "INSERT INTO prototype_assessment_result_history (history_id, organization_id, assessment_id, student_id, change_type, previous_score, previous_comment, new_score, new_comment) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (history_id, organization_id, assessment_id, student_id, change_type, previous_score, previous_comment, score, comment),
        )
        row = conn.execute("SELECT * FROM prototype_assessment_results WHERE organization_id = ? AND result_id = ?", (organization_id, result_id)).fetchone()
    return dict(row) if row else None


def list_assessment_result_history(organization_id: str, assessment_id: str, student_id: str) -> list[dict[str, Any]] | None:
    """Return draft-time score change history within the assessment's organization."""
    with db_session() as conn:
        exists = conn.execute(
            "SELECT 1 FROM prototype_assessments WHERE organization_id = ? AND assessment_id = ?",
            (organization_id, assessment_id),
        ).fetchone()
        if not exists:
            return None
        rows = conn.execute(
            "SELECT history_id, organization_id, assessment_id, student_id, change_type, previous_score, previous_comment, new_score, new_comment, changed_at "
            "FROM prototype_assessment_result_history WHERE organization_id = ? AND assessment_id = ? AND student_id = ? "
            "ORDER BY changed_at ASC, rowid ASC",
            (organization_id, assessment_id, student_id),
        ).fetchall()
    return [dict(row) for row in rows]


def list_assessment_results(organization_id: str, assessment_id: str) -> list[dict[str, Any]] | None:
    with db_session() as conn:
        exists = conn.execute("SELECT 1 FROM prototype_assessments WHERE organization_id = ? AND assessment_id = ?", (organization_id, assessment_id)).fetchone()
        if not exists:
            return None
        rows = conn.execute("SELECT r.*, s.given_name, s.middle_name, s.family_name FROM prototype_assessment_results r JOIN prototype_students s ON s.organization_id = r.organization_id AND s.student_id = r.student_id WHERE r.organization_id = ? AND r.assessment_id = ? ORDER BY s.family_name, s.given_name", (organization_id, assessment_id)).fetchall()
    return [dict(row) for row in rows]


def publish_assessment(organization_id: str, assessment_id: str) -> dict[str, Any] | None:
    with db_session() as conn:
        row = conn.execute("SELECT * FROM prototype_assessments WHERE organization_id = ? AND assessment_id = ?", (organization_id, assessment_id)).fetchone()
        if not row:
            return None
        if row["status"] == "published":
            return dict(row)
        count = conn.execute("SELECT COUNT(*) FROM prototype_assessment_results WHERE organization_id = ? AND assessment_id = ?", (organization_id, assessment_id)).fetchone()[0]
        if count == 0:
            raise ValueError("At least one student result is required before publishing")
        conn.execute("UPDATE prototype_assessments SET status = 'published', published_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE organization_id = ? AND assessment_id = ? AND status = 'draft'", (organization_id, assessment_id))
        updated = conn.execute("SELECT * FROM prototype_assessments WHERE organization_id = ? AND assessment_id = ?", (organization_id, assessment_id)).fetchone()
    return dict(updated) if updated else None


def build_student_report_card(organization_id: str, student_id: str, section_id: str, term: str) -> dict[str, Any] | None:
    """Build a draft-safe report view from published assessments for an active enrollment.

    Missing scores remain null and are excluded from aggregate denominators; they are not
    silently treated as zero. This is a prototype projection, not an immutable report snapshot.
    """
    from decimal import Decimal, ROUND_HALF_UP
    with db_session() as conn:
        enrollment = conn.execute(
            "SELECT s.student_id, s.given_name, s.middle_name, s.family_name, s.branch_id, "
            "e.section_id, c.name AS section_name, c.year_id, l.name AS class_level, y.name AS academic_year "
            "FROM prototype_enrollments e "
            "JOIN prototype_students s ON s.organization_id=e.organization_id AND s.student_id=e.student_id "
            "JOIN prototype_sections c ON c.organization_id=e.organization_id AND c.section_id=e.section_id "
            "JOIN prototype_class_levels l ON l.organization_id=c.organization_id AND l.level_id=c.level_id "
            "JOIN prototype_academic_years y ON y.organization_id=c.organization_id AND y.year_id=c.year_id "
            "WHERE e.organization_id=? AND e.student_id=? AND e.section_id=? "
            "AND e.status='active' AND s.status='active' AND c.status='active'",
            (organization_id, student_id, section_id),
        ).fetchone()
        if not enrollment:
            return None
        rows = conn.execute(
            "SELECT a.assessment_id, a.subject, a.title, a.term, a.assessment_date, a.max_score, "
            "a.published_at, r.score, r.comment, r.updated_at AS result_updated_at "
            "FROM prototype_assessments a LEFT JOIN prototype_assessment_results r "
            "ON r.organization_id=a.organization_id AND r.assessment_id=a.assessment_id AND r.student_id=? "
            "WHERE a.organization_id=? AND a.section_id=? AND a.term=? AND a.status='published' "
            "ORDER BY a.subject, a.assessment_date, a.title, a.assessment_id",
            (student_id, organization_id, section_id, term),
        ).fetchall()
    assessments = []
    earned_total = Decimal('0')
    max_total = Decimal('0')
    scored_count = 0
    for row in rows:
        item = dict(row)
        item['max_score'] = str(Decimal(item['max_score']))
        if item['score'] is not None:
            item['score'] = str(Decimal(item['score']))
            earned_total += Decimal(item['score'])
            max_total += Decimal(item['max_score'])
            scored_count += 1
            item['percentage'] = str((Decimal(item['score']) / Decimal(item['max_score']) * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
        else:
            item['percentage'] = None
        assessments.append(item)
    percentage = None if max_total == 0 else str((earned_total / max_total * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    student = dict(enrollment)
    return {
        'student': {key: student[key] for key in ('student_id', 'given_name', 'middle_name', 'family_name', 'branch_id')},
        'section': {key: student[key] for key in ('section_id', 'section_name', 'class_level', 'academic_year')},
        'term': term,
        'assessments': assessments,
        'summary': {
            'published_assessment_count': len(assessments),
            'scored_assessment_count': scored_count,
            'missing_score_count': len(assessments) - scored_count,
            'total_score': str(earned_total),
            'total_max_score': str(max_total),
            'percentage': percentage,
        },
        'prototype_only': True,
    }


def list_students_for_assessment(organization_id: str, branch_id: str, section_id: str | None = None) -> list[dict[str, Any]]:
    with db_session() as conn:
        if section_id:
            section = conn.execute(
                "SELECT 1 FROM prototype_sections WHERE organization_id = ? AND section_id = ? AND branch_id = ?",
                (organization_id, section_id, branch_id),
            ).fetchone()
            if not section:
                return []
            rows = conn.execute(
                "SELECT s.student_id, s.given_name, s.middle_name, s.family_name, s.branch_id "
                "FROM prototype_enrollments e JOIN prototype_students s ON s.organization_id=e.organization_id AND s.student_id=e.student_id "
                "WHERE e.organization_id = ? AND e.section_id = ? AND e.status = 'active' AND s.status = 'active' "
                "ORDER BY s.family_name, s.given_name",
                (organization_id, section_id),
            ).fetchall()
        else:
            rows = conn.execute("SELECT student_id, given_name, middle_name, family_name, branch_id FROM prototype_students WHERE organization_id = ? AND branch_id = ? AND status = 'active' ORDER BY family_name, given_name", (organization_id, branch_id)).fetchall()
    return [dict(row) for row in rows]


def list_students(
    organization_id: str,
    branch_id: str | None,
    limit: int,
    offset: int,
    query: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List organization-scoped students with optional literal substring search."""
    with db_session() as conn:
        where = "organization_id = ?"
        args: list[Any] = [organization_id]
        if branch_id:
            where += " AND branch_id = ?"
            args.append(branch_id)
        normalized_query = query.strip() if query else ""
        if normalized_query:
            # Escape SQL LIKE metacharacters so search text is interpreted literally.
            escaped = normalized_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where += " AND (given_name LIKE ? ESCAPE '\\' COLLATE NOCASE OR middle_name LIKE ? ESCAPE '\\' COLLATE NOCASE OR family_name LIKE ? ESCAPE '\\' COLLATE NOCASE OR external_reference LIKE ? ESCAPE '\\' COLLATE NOCASE OR student_id LIKE ? ESCAPE '\\' COLLATE NOCASE)"
            pattern = f"%{escaped}%"
            args.extend([pattern] * 5)
        total = conn.execute(f"SELECT COUNT(*) FROM prototype_students WHERE {where}", args).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM prototype_students WHERE {where} ORDER BY family_name COLLATE NOCASE, given_name COLLATE NOCASE, student_id LIMIT ? OFFSET ?",
            [*args, limit, offset],
        ).fetchall()
    return [dict(row) for row in rows], total


def get_student(organization_id: str, student_id: str) -> dict[str, Any] | None:
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM prototype_students WHERE organization_id = ? AND student_id = ?",
            (organization_id, student_id),
        ).fetchone()
    return dict(row) if row else None


def create_student(student: dict[str, Any]) -> dict[str, Any]:
    columns = ["student_id", "organization_id", "branch_id", "given_name", "middle_name", "family_name", "date_of_birth", "sex_at_registration", "external_reference", "status"]
    with db_session() as conn:
        conn.execute(
            f"INSERT INTO prototype_students ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            [student.get(column) for column in columns],
        )
    return get_student(student["organization_id"], student["student_id"]) or student


def update_student(organization_id: str, student_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"given_name", "middle_name", "family_name", "date_of_birth", "sex_at_registration", "external_reference"}
    changes = {key: value for key, value in changes.items() if key in allowed}
    if not changes:
        return get_student(organization_id, student_id)
    assignments = ", ".join(f"{key} = ?" for key in changes)
    values = list(changes.values()) + [organization_id, student_id]
    with db_session() as conn:
        cursor = conn.execute(
            f"UPDATE prototype_students SET {assignments} WHERE organization_id = ? AND student_id = ?",
            values,
        )
        if cursor.rowcount == 0:
            return None
    return get_student(organization_id, student_id)


def deactivate_student(organization_id: str, student_id: str, reason: str) -> tuple[dict[str, Any] | None, bool]:
    """Deactivate a student and append the reason to the audit trail atomically."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM prototype_students WHERE organization_id = ? AND student_id = ?",
            (organization_id, student_id),
        ).fetchone()
        if row is None:
            return None, False
        student = dict(row)
        if student["status"] != "active":
            return student, False
        conn.execute(
            "UPDATE prototype_students SET status = 'inactive' WHERE organization_id = ? AND student_id = ? AND status = 'active'",
            (organization_id, student_id),
        )
        _record_audit_event_conn(
            conn, organization_id, "student.deactivated", "student", student_id,
            details={"reason": reason.strip(), "previous_status": "active", "new_status": "inactive"},
        )
        updated = conn.execute(
            "SELECT * FROM prototype_students WHERE organization_id = ? AND student_id = ?",
            (organization_id, student_id),
        ).fetchone()
    return dict(updated), True


def add_guardian(organization_id: str, student_id: str, guardian: dict[str, Any]) -> dict[str, Any] | None:
    import uuid
    with db_session() as conn:
        exists = conn.execute(
            "SELECT 1 FROM prototype_students WHERE organization_id = ? AND student_id = ?",
            (organization_id, student_id),
        ).fetchone()
        if not exists:
            return None
        guardian_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO prototype_guardians (guardian_id, organization_id, given_name, family_name, phone, email) VALUES (?, ?, ?, ?, ?, ?)",
            (guardian_id, organization_id, guardian["given_name"], guardian["family_name"], guardian.get("phone"), guardian.get("email")),
        )
        conn.execute(
            "INSERT INTO prototype_student_guardians (organization_id, student_id, guardian_id, relationship, is_primary) VALUES (?, ?, ?, ?, ?)",
            (organization_id, student_id, guardian_id, guardian["relationship"], int(guardian.get("is_primary", False))),
        )
        row = conn.execute(
            "SELECT g.guardian_id, g.organization_id, sg.student_id, g.given_name, g.family_name, sg.relationship, g.phone, g.email, sg.is_primary, sg.portal_access, g.created_at FROM prototype_guardians g JOIN prototype_student_guardians sg ON sg.organization_id = g.organization_id AND sg.guardian_id = g.guardian_id WHERE sg.organization_id = ? AND sg.student_id = ? AND sg.guardian_id = ?",
            (organization_id, student_id, guardian_id),
        ).fetchone()
    return dict(row) if row else None

def search_guardian_directory(organization_id: str, search: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Search guardian identities within one organization; never returns linked student details."""
    predicate = "g.organization_id = ?"
    args: list[Any] = [organization_id]
    if search and search.strip():
        # Escape LIKE metacharacters so user input is treated as literal search text.
        term = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        predicate += " AND (g.given_name LIKE ? ESCAPE '\\' OR g.family_name LIKE ? ESCAPE '\\' OR COALESCE(g.phone, '') LIKE ? ESCAPE '\\' OR COALESCE(g.email, '') LIKE ? ESCAPE '\\')"
        pattern = f"%{term}%"
        args.extend([pattern] * 4)
    with db_session() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM prototype_guardians g WHERE {predicate}", args).fetchone()[0]
        rows = conn.execute(
            f"""SELECT g.guardian_id, g.organization_id, g.given_name, g.family_name,
                       g.phone, g.email, g.created_at,
                       (SELECT COUNT(*) FROM prototype_student_guardians sg
                        WHERE sg.organization_id = g.organization_id AND sg.guardian_id = g.guardian_id) AS linked_student_count
                FROM prototype_guardians g WHERE {predicate}
                ORDER BY g.family_name COLLATE NOCASE, g.given_name COLLATE NOCASE, g.guardian_id
                LIMIT ? OFFSET ?""",
            [*args, limit, offset],
        ).fetchall()
    return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


def list_guardians(organization_id: str, student_id: str) -> list[dict[str, Any]] | None:
    with db_session() as conn:
        exists = conn.execute("SELECT 1 FROM prototype_students WHERE organization_id = ? AND student_id = ?", (organization_id, student_id)).fetchone()
        if not exists:
            return None
        rows = conn.execute(
            "SELECT g.guardian_id, g.organization_id, sg.student_id, g.given_name, g.family_name, sg.relationship, g.phone, g.email, sg.is_primary, sg.portal_access, g.created_at FROM prototype_guardians g JOIN prototype_student_guardians sg ON sg.organization_id = g.organization_id AND sg.guardian_id = g.guardian_id WHERE sg.organization_id = ? AND sg.student_id = ? ORDER BY sg.is_primary DESC, g.family_name, g.given_name",
            (organization_id, student_id),
        ).fetchall()
    return [dict(row) for row in rows]


# Attendance functions below are prototype-only; identity of the actor is not yet authenticated.
def create_attendance(record: dict[str, Any]) -> dict[str, Any] | None:
    import uuid
    with db_session() as conn:
        student = conn.execute(
            "SELECT branch_id FROM prototype_students WHERE organization_id = ? AND student_id = ?",
            (record["organization_id"], record["student_id"]),
        ).fetchone()
        if not student:
            return None
        attendance_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO prototype_attendance (attendance_id, organization_id, branch_id, student_id, attendance_date, status, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (attendance_id, record["organization_id"], student["branch_id"], record["student_id"], record["attendance_date"], record["status"], record.get("note")),
        )
        row = conn.execute("SELECT * FROM prototype_attendance WHERE attendance_id = ?", (attendance_id,)).fetchone()
    return dict(row) if row else None



def create_attendance_bulk(organization_id: str, attendance_date: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create a complete class register atomically; no partial writes on validation failure."""
    import uuid
    created_ids: list[str] = []
    with db_session() as conn:
        for record in records:
            student = conn.execute(
                "SELECT branch_id FROM prototype_students WHERE organization_id = ? AND student_id = ?",
                (organization_id, record["student_id"]),
            ).fetchone()
            if not student:
                raise LookupError(record["student_id"])
            attendance_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO prototype_attendance (attendance_id, organization_id, branch_id, student_id, attendance_date, status, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (attendance_id, organization_id, student["branch_id"], record["student_id"], attendance_date, record["status"], record.get("note")),
            )
            created_ids.append(attendance_id)
        placeholders = ",".join("?" for _ in created_ids)
        rows = conn.execute(
            f"SELECT * FROM prototype_attendance WHERE organization_id = ? AND attendance_id IN ({placeholders}) ORDER BY created_at, student_id",
            [organization_id, *created_ids],
        ).fetchall()
    return [dict(row) for row in rows]

def list_attendance(organization_id: str, attendance_date: str | None, branch_id: str | None, student_id: str | None, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    where = ["organization_id = ?"]
    args: list[Any] = [organization_id]
    if attendance_date:
        where.append("attendance_date = ?")
        args.append(attendance_date)
    if branch_id:
        where.append("branch_id = ?")
        args.append(branch_id)
    if student_id:
        where.append("student_id = ?")
        args.append(student_id)
    clause = " AND ".join(where)
    with db_session() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM prototype_attendance WHERE {clause}", args).fetchone()[0]
        rows = conn.execute(f"SELECT * FROM prototype_attendance WHERE {clause} ORDER BY attendance_date DESC, created_at DESC LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
    return [dict(row) for row in rows], total



def attendance_student_report(organization_id: str, start_date: str, end_date: str, branch_id: str | None, limit: int, offset: int) -> dict[str, Any]:
    """Per-student attendance counts for a date range; students without records remain visible."""
    student_where = ["s.organization_id = ?", "s.status = 'active'"]
    student_args: list[Any] = [organization_id]
    if branch_id:
        student_where.append("s.branch_id = ?")
        student_args.append(branch_id)
    student_clause = " AND ".join(student_where)
    with db_session() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM prototype_students s WHERE {student_clause}", student_args
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT s.student_id, s.branch_id, s.given_name, s.middle_name, s.family_name, "
            "COUNT(a.attendance_id) AS total_recorded, "
            "SUM(CASE WHEN a.status = 'present' THEN 1 ELSE 0 END) AS present, "
            "SUM(CASE WHEN a.status = 'absent' THEN 1 ELSE 0 END) AS absent, "
            "SUM(CASE WHEN a.status = 'late' THEN 1 ELSE 0 END) AS late, "
            "SUM(CASE WHEN a.status = 'excused' THEN 1 ELSE 0 END) AS excused "
            "FROM prototype_students s "
            "LEFT JOIN prototype_attendance a ON a.organization_id = s.organization_id "
            "AND a.student_id = s.student_id AND a.attendance_date >= ? AND a.attendance_date <= ? "
            f"WHERE {student_clause} "
            "GROUP BY s.student_id, s.branch_id, s.given_name, s.middle_name, s.family_name "
            "ORDER BY s.family_name COLLATE NOCASE, s.given_name COLLATE NOCASE, s.student_id "
            "LIMIT ? OFFSET ?",
            [start_date, end_date, *student_args, limit, offset],
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        recorded = int(item["total_recorded"] or 0)
        for key in ("present", "absent", "late", "excused"):
            item[key] = int(item[key] or 0)
        item["total_recorded"] = recorded
        denominator = recorded - item["excused"]
        item["attendance_rate_pct"] = round(((item["present"] + item["late"]) / denominator) * 100, 2) if denominator else None
        item["full_name"] = " ".join(part for part in (item.pop("given_name"), item.pop("middle_name"), item.pop("family_name")) if part)
        items.append(item)
    return {
        "organization_id": organization_id,
        "start_date": start_date,
        "end_date": end_date,
        "branch_id": branch_id,
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "rate_definition": "(present + late) / (total_recorded - excused) * 100; null when denominator is zero",
        "note": "Counts include recorded attendance only; no record does not mean absent.",
    }


def attendance_summary(organization_id: str, start_date: str, end_date: str, branch_id: str | None = None) -> dict[str, Any]:
    """Aggregate recorded attendance; this is not a measure of unrecorded school days."""
    where = ["organization_id = ?", "attendance_date >= ?", "attendance_date <= ?"]
    args: list[Any] = [organization_id, start_date, end_date]
    if branch_id:
        where.append("branch_id = ?")
        args.append(branch_id)
    clause = " AND ".join(where)
    with db_session() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS total_recorded, "
            "SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present, "
            "SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) AS absent, "
            "SUM(CASE WHEN status = 'late' THEN 1 ELSE 0 END) AS late, "
            "SUM(CASE WHEN status = 'excused' THEN 1 ELSE 0 END) AS excused "
            f"FROM prototype_attendance WHERE {clause}", args
        ).fetchone()
    total = int(row["total_recorded"] or 0)
    present = int(row["present"] or 0)
    absent = int(row["absent"] or 0)
    late = int(row["late"] or 0)
    excused = int(row["excused"] or 0)
    denominator = total - excused
    rate = round(((present + late) / denominator) * 100, 2) if denominator else None
    return {
        "organization_id": organization_id,
        "start_date": start_date,
        "end_date": end_date,
        "branch_id": branch_id,
        "total_recorded": total,
        "present": present,
        "absent": absent,
        "late": late,
        "excused": excused,
        "attendance_rate_pct": rate,
        "rate_definition": "(present + late) / (total_recorded - excused) * 100; null when denominator is zero",
    }


def update_attendance(organization_id: str, attendance_id: str, status: str, note: str | None, reason: str) -> dict[str, Any] | None:
    import uuid
    with db_session() as conn:
        row = conn.execute("SELECT * FROM prototype_attendance WHERE organization_id = ? AND attendance_id = ?", (organization_id, attendance_id)).fetchone()
        if not row:
            return None
        conn.execute(
            "INSERT INTO prototype_attendance_changes (change_id, organization_id, attendance_id, old_status, new_status, reason) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), organization_id, attendance_id, row["status"], status, reason),
        )
        conn.execute(
            "UPDATE prototype_attendance SET status = ?, note = ?, version = version + 1, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE organization_id = ? AND attendance_id = ?",
            (status, note, organization_id, attendance_id),
        )
        updated = conn.execute("SELECT * FROM prototype_attendance WHERE organization_id = ? AND attendance_id = ?", (organization_id, attendance_id)).fetchone()
    return dict(updated) if updated else None


def attendance_history(organization_id: str, attendance_id: str) -> list[dict[str, Any]] | None:
    with db_session() as conn:
        exists = conn.execute("SELECT 1 FROM prototype_attendance WHERE organization_id = ? AND attendance_id = ?", (organization_id, attendance_id)).fetchone()
        if not exists:
            return None
        rows = conn.execute("SELECT change_id, old_status, new_status, reason, changed_at FROM prototype_attendance_changes WHERE organization_id = ? AND attendance_id = ? ORDER BY changed_at, change_id", (organization_id, attendance_id)).fetchall()
    return [dict(row) for row in rows]


def link_existing_guardian(organization_id: str, student_id: str, guardian_id: str, relationship: str, is_primary: bool) -> dict[str, Any] | None:
    with db_session() as conn:
        student = conn.execute("SELECT 1 FROM prototype_students WHERE organization_id = ? AND student_id = ?", (organization_id, student_id)).fetchone()
        guardian = conn.execute("SELECT 1 FROM prototype_guardians WHERE organization_id = ? AND guardian_id = ?", (organization_id, guardian_id)).fetchone()
        if not student or not guardian:
            return None
        conn.execute("INSERT INTO prototype_student_guardians (organization_id, student_id, guardian_id, relationship, is_primary) VALUES (?, ?, ?, ?, ?)", (organization_id, student_id, guardian_id, relationship, int(is_primary)))
        row = conn.execute("SELECT g.guardian_id, g.organization_id, sg.student_id, g.given_name, g.family_name, sg.relationship, g.phone, g.email, sg.is_primary, sg.portal_access, g.created_at FROM prototype_guardians g JOIN prototype_student_guardians sg ON sg.organization_id = g.organization_id AND sg.guardian_id = g.guardian_id WHERE sg.organization_id = ? AND sg.student_id = ? AND sg.guardian_id = ?", (organization_id, student_id, guardian_id)).fetchone()
    return dict(row) if row else None


def create_academic_year(payload: dict[str, Any]) -> dict[str, Any]:
    import uuid
    year = {**payload, "year_id": str(uuid.uuid4())}
    with db_session() as conn:
        conn.execute("INSERT INTO prototype_academic_years (year_id, organization_id, name, start_date, end_date) VALUES (?, ?, ?, ?, ?)", (year["year_id"], year["organization_id"], year["name"], year["start_date"], year["end_date"]))
    return get_academic_year(year["organization_id"], year["year_id"]) or year


def get_academic_year(organization_id: str, year_id: str) -> dict[str, Any] | None:
    with db_session() as conn:
        row = conn.execute("SELECT * FROM prototype_academic_years WHERE organization_id = ? AND year_id = ?", (organization_id, year_id)).fetchone()
    return dict(row) if row else None


def list_academic_years(organization_id: str) -> list[dict[str, Any]]:
    with db_session() as conn:
        rows = conn.execute("SELECT * FROM prototype_academic_years WHERE organization_id = ? ORDER BY start_date DESC, name", (organization_id,)).fetchall()
    return [dict(row) for row in rows]


def create_class_level(payload: dict[str, Any]) -> dict[str, Any]:
    import uuid
    item = {**payload, "level_id": str(uuid.uuid4())}
    with db_session() as conn:
        conn.execute("INSERT INTO prototype_class_levels (level_id, organization_id, name, sort_order) VALUES (?, ?, ?, ?)", (item["level_id"], item["organization_id"], item["name"], item["sort_order"]))
        row = conn.execute("SELECT * FROM prototype_class_levels WHERE organization_id = ? AND level_id = ?", (item["organization_id"], item["level_id"])).fetchone()
    return dict(row)


def list_class_levels(organization_id: str) -> list[dict[str, Any]]:
    with db_session() as conn:
        rows = conn.execute("SELECT * FROM prototype_class_levels WHERE organization_id = ? ORDER BY sort_order, name", (organization_id,)).fetchall()
    return [dict(row) for row in rows]


def create_section(payload: dict[str, Any]) -> dict[str, Any]:
    import uuid
    item = {**payload, "section_id": str(uuid.uuid4())}
    with db_session() as conn:
        conn.execute("INSERT INTO prototype_sections (section_id, organization_id, branch_id, year_id, level_id, name, capacity) VALUES (?, ?, ?, ?, ?, ?, ?)", (item["section_id"], item["organization_id"], item["branch_id"], item["year_id"], item["level_id"], item["name"], item.get("capacity")))
        row = conn.execute("SELECT s.*, y.name AS academic_year, l.name AS class_level FROM prototype_sections s JOIN prototype_academic_years y ON y.organization_id=s.organization_id AND y.year_id=s.year_id JOIN prototype_class_levels l ON l.organization_id=s.organization_id AND l.level_id=s.level_id WHERE s.organization_id = ? AND s.section_id = ?", (item["organization_id"], item["section_id"])).fetchone()
    return dict(row)


def list_sections(organization_id: str, branch_id: str | None = None, year_id: str | None = None) -> list[dict[str, Any]]:
    where = ["s.organization_id = ?"]
    args: list[Any] = [organization_id]
    if branch_id:
        where.append("s.branch_id = ?"); args.append(branch_id)
    if year_id:
        where.append("s.year_id = ?"); args.append(year_id)
    with db_session() as conn:
        rows = conn.execute("SELECT s.*, y.name AS academic_year, l.name AS class_level FROM prototype_sections s JOIN prototype_academic_years y ON y.organization_id=s.organization_id AND y.year_id=s.year_id JOIN prototype_class_levels l ON l.organization_id=s.organization_id AND l.level_id=s.level_id WHERE " + " AND ".join(where) + " ORDER BY s.branch_id, y.start_date DESC, l.sort_order, s.name", args).fetchall()
    return [dict(row) for row in rows]


def create_enrollment(organization_id: str, student_id: str, section_id: str, enrolled_on: str) -> dict[str, Any]:
    import uuid
    with db_session() as conn:
        student = conn.execute("SELECT branch_id, status FROM prototype_students WHERE organization_id = ? AND student_id = ?", (organization_id, student_id)).fetchone()
        section = conn.execute("SELECT branch_id, status, capacity FROM prototype_sections WHERE organization_id = ? AND section_id = ?", (organization_id, section_id)).fetchone()
        if not student:
            raise LookupError("student")
        if not section:
            raise LookupError("section")
        if student["status"] != "active":
            raise ValueError("Only active students can be enrolled")
        if section["status"] != "active":
            raise ValueError("Cannot enroll into an archived section")
        if student["branch_id"] != section["branch_id"]:
            raise ValueError("Student and section must belong to the same branch")
        if section["capacity"] is not None:
            count = conn.execute("SELECT COUNT(*) FROM prototype_enrollments WHERE organization_id = ? AND section_id = ? AND status = 'active'", (organization_id, section_id)).fetchone()[0]
            if count >= section["capacity"]:
                raise OverflowError("Section capacity has been reached")
        enrollment_id = str(uuid.uuid4())
        conn.execute("INSERT INTO prototype_enrollments (enrollment_id, organization_id, student_id, section_id, enrolled_on) VALUES (?, ?, ?, ?, ?)", (enrollment_id, organization_id, student_id, section_id, enrolled_on))
        row = conn.execute("SELECT e.*, s.given_name, s.middle_name, s.family_name, c.name AS section_name, c.branch_id, l.name AS class_level, y.name AS academic_year FROM prototype_enrollments e JOIN prototype_students s ON s.organization_id=e.organization_id AND s.student_id=e.student_id JOIN prototype_sections c ON c.organization_id=e.organization_id AND c.section_id=e.section_id JOIN prototype_class_levels l ON l.organization_id=c.organization_id AND l.level_id=c.level_id JOIN prototype_academic_years y ON y.organization_id=c.organization_id AND y.year_id=c.year_id WHERE e.organization_id = ? AND e.enrollment_id = ?", (organization_id, enrollment_id)).fetchone()
    return dict(row)


def list_students_for_section(organization_id: str, section_id: str) -> list[dict[str, Any]] | None:
    """Return active students currently enrolled in a section; None means section is missing."""
    with db_session() as conn:
        section = conn.execute(
            "SELECT section_id FROM prototype_sections WHERE organization_id = ? AND section_id = ?",
            (organization_id, section_id),
        ).fetchone()
        if not section:
            return None
        rows = conn.execute(
            "SELECT s.student_id, s.given_name, s.middle_name, s.family_name, s.branch_id, e.enrollment_id, e.enrolled_on "
            "FROM prototype_enrollments e JOIN prototype_students s "
            "ON s.organization_id = e.organization_id AND s.student_id = e.student_id "
            "WHERE e.organization_id = ? AND e.section_id = ? AND e.status = 'active' AND s.status = 'active' "
            "ORDER BY s.family_name, s.given_name, s.student_id",
            (organization_id, section_id),
        ).fetchall()
    return [dict(row) for row in rows]


def create_section_attendance_bulk(organization_id: str, section_id: str, attendance_date: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Atomically record attendance only for active students enrolled in the specified section."""
    import uuid
    created_ids: list[str] = []
    with db_session() as conn:
        section = conn.execute(
            "SELECT branch_id, status FROM prototype_sections WHERE organization_id = ? AND section_id = ?",
            (organization_id, section_id),
        ).fetchone()
        if not section:
            raise LookupError("section")
        if section["status"] != "active":
            raise ValueError("Cannot record attendance for an archived section")
        for record in records:
            enrollment = conn.execute(
                "SELECT 1 FROM prototype_enrollments e JOIN prototype_students s "
                "ON s.organization_id = e.organization_id AND s.student_id = e.student_id "
                "WHERE e.organization_id = ? AND e.section_id = ? AND e.student_id = ? "
                "AND e.status = 'active' AND s.status = 'active'",
                (organization_id, section_id, record["student_id"]),
            ).fetchone()
            if not enrollment:
                raise LookupError(f"student {record['student_id']} is not actively enrolled in section {section_id}")
            attendance_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO prototype_attendance (attendance_id, organization_id, branch_id, student_id, attendance_date, status, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (attendance_id, organization_id, section["branch_id"], record["student_id"], attendance_date, record["status"], record.get("note")),
            )
            created_ids.append(attendance_id)
        placeholders = ",".join("?" for _ in created_ids)
        rows = conn.execute(
            f"SELECT * FROM prototype_attendance WHERE organization_id = ? AND attendance_id IN ({placeholders}) ORDER BY created_at, student_id",
            [organization_id, *created_ids],
        ).fetchall()
    return [dict(row) for row in rows]


def list_enrollments(organization_id: str, section_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    where = ["e.organization_id = ?"]
    args: list[Any] = [organization_id]
    if section_id:
        where.append("e.section_id = ?"); args.append(section_id)
    if status:
        where.append("e.status = ?"); args.append(status)
    with db_session() as conn:
        rows = conn.execute("SELECT e.*, s.given_name, s.middle_name, s.family_name, c.name AS section_name, c.branch_id, l.name AS class_level, y.name AS academic_year FROM prototype_enrollments e JOIN prototype_students s ON s.organization_id=e.organization_id AND s.student_id=e.student_id JOIN prototype_sections c ON c.organization_id=e.organization_id AND c.section_id=e.section_id JOIN prototype_class_levels l ON l.organization_id=c.organization_id AND l.level_id=c.level_id JOIN prototype_academic_years y ON y.organization_id=c.organization_id AND y.year_id=c.year_id WHERE " + " AND ".join(where) + " ORDER BY c.name, s.family_name, s.given_name", args).fetchall()
    return [dict(row) for row in rows]


def _ensure_finance_system_accounts(conn: sqlite3.Connection, organization_id: str, currency: str) -> dict[str, str]:
    """Create/resolve prototype accounts used by automatic fee postings."""
    definitions = [
        ("1000", "Cash and payment clearing", "asset"),
        ("1100", "Student accounts receivable", "asset"),
        ("2100", "Student credit liability", "liability"),
        ("4000", "Tuition and fee revenue", "revenue"),
    ]
    resolved: dict[str, str] = {}
    import uuid
    for code, name, account_type in definitions:
        row = conn.execute(
            "SELECT account_id, account_type FROM prototype_ledger_accounts WHERE organization_id=? AND code=? AND currency=?",
            (organization_id, code, currency),
        ).fetchone()
        if row:
            if row["account_type"] != account_type:
                raise ValueError(f"Reserved ledger account code {code} must have type {account_type}")
            resolved[code] = row["account_id"]
            continue
        # Codes are organization-wide unique; a code with another currency still conflicts.
        any_currency = conn.execute(
            "SELECT account_id, account_type, currency FROM prototype_ledger_accounts WHERE organization_id=? AND code=?",
            (organization_id, code),
        ).fetchone()
        if any_currency:
            raise ValueError(f"Reserved ledger account code {code} already exists with currency {any_currency['currency']}")
        account_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO prototype_ledger_accounts (account_id, organization_id, code, name, account_type, currency) VALUES (?,?,?,?,?,?)",
            (account_id, organization_id, code, name, account_type, currency),
        )
        resolved[code] = account_id
    return resolved


def _post_system_journal(conn: sqlite3.Connection, organization_id: str, description: str, currency: str, lines: list[dict[str, Any]]) -> str:
    """Insert a balanced system journal inside the caller's business transaction."""
    import uuid
    debits = sum(line["debit_minor"] for line in lines)
    credits = sum(line["credit_minor"] for line in lines)
    if debits <= 0 or debits != credits:
        raise ValueError("System journal must be balanced and non-zero")
    journal_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO prototype_ledger_journals (journal_id, organization_id, description, currency) VALUES (?,?,?,?)",
        (journal_id, organization_id, description, currency),
    )
    for number, line in enumerate(lines, 1):
        conn.execute(
            "INSERT INTO prototype_ledger_lines (organization_id, journal_id, line_number, account_id, debit_minor, credit_minor) VALUES (?,?,?,?,?,?)",
            (organization_id, journal_id, number, line["account_id"], line["debit_minor"], line["credit_minor"]),
        )
    return journal_id


def _record_audit_event_conn(
    conn: sqlite3.Connection, organization_id: str, event_type: str, entity_type: str,
    entity_id: str, details: dict[str, Any] | None = None, actor_id: str | None = None,
    source: str = "api-prototype",
) -> dict[str, Any]:
    """Append an event using the caller's transaction, so audit and business writes commit together."""
    import uuid
    event_id = str(uuid.uuid4())
    safe_details = json.dumps(details or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    conn.execute(
        "INSERT INTO prototype_audit_events (event_id, organization_id, event_type, entity_type, entity_id, actor_id, source, details_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (event_id, organization_id, event_type, entity_type, entity_id, actor_id, source, safe_details),
    )
    row = conn.execute("SELECT * FROM prototype_audit_events WHERE organization_id=? AND event_id=?", (organization_id, event_id)).fetchone()
    result = dict(row)
    result["details"] = json.loads(result.pop("details_json"))
    return result


def record_audit_event(
    organization_id: str, event_type: str, entity_type: str, entity_id: str,
    details: dict[str, Any] | None = None, actor_id: str | None = None,
    source: str = "api-prototype",
) -> dict[str, Any]:
    """Append a standalone tenant-scoped event; no user identity is inferred."""
    with db_session() as conn:
        return _record_audit_event_conn(conn, organization_id, event_type, entity_type, entity_id, details, actor_id, source)


def list_audit_events(
    organization_id: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    event_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Read audit history for one organization with bounded pagination."""
    where = ["organization_id=?"]
    args: list[Any] = [organization_id]
    for column, value in (("entity_type", entity_type), ("entity_id", entity_id), ("event_type", event_type)):
        if value is not None:
            where.append(f"{column}=?")
            args.append(value)
    predicate = " AND ".join(where)
    with db_session() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM prototype_audit_events WHERE {predicate}", args).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM prototype_audit_events WHERE {predicate} ORDER BY created_at DESC, event_id DESC LIMIT ? OFFSET ?",
            [*args, limit, offset],
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["details"] = json.loads(item.pop("details_json"))
        items.append(item)
    return {"items": items, "total": total, "limit": limit, "offset": offset, "prototype_only": True}


def create_fee_bill(organization_id: str, payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
    """Create a bill once per optional tenant-scoped idempotency key."""
    import uuid
    bill_id = str(uuid.uuid4())
    with db_session() as conn:
        # Acquire the SQLite write lock before checking the idempotency key.
        # This serializes concurrent retries so only one request can create the record.
        conn.execute("BEGIN IMMEDIATE")
        if idempotency_key:
            replay = _idempotency_replay(conn, organization_id, "fee_bill.create", idempotency_key, payload)
            if replay is not None:
                return replay
        student = conn.execute("SELECT student_id FROM prototype_students WHERE organization_id=? AND student_id=?", (organization_id, payload["student_id"])).fetchone()
        if not student:
            raise LookupError("student")
        conn.execute(
            "INSERT INTO prototype_fee_bills (bill_id, organization_id, student_id, description, amount_minor, currency, due_date) VALUES (?,?,?,?,?,?,?)",
            (bill_id, organization_id, payload["student_id"], payload["description"], payload["amount_minor"], payload["currency"], payload.get("due_date")),
        )
        conn.execute(
            "INSERT INTO prototype_student_account_entries (entry_id, organization_id, student_id, entry_type, amount_minor, currency, bill_id) VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), organization_id, payload["student_id"], "fee_charge", payload["amount_minor"], payload["currency"], bill_id),
        )
        accounts = _ensure_finance_system_accounts(conn, organization_id, payload["currency"])
        _post_system_journal(conn, organization_id, f"Fee bill {bill_id}", payload["currency"], [
            {"account_id": accounts["1100"], "debit_minor": payload["amount_minor"], "credit_minor": 0},
            {"account_id": accounts["4000"], "debit_minor": 0, "credit_minor": payload["amount_minor"]},
        ])
        row = conn.execute("SELECT * FROM prototype_fee_bills WHERE organization_id=? AND bill_id=?", (organization_id, bill_id)).fetchone()
        result = dict(row)
        _record_audit_event_conn(conn, organization_id, "finance.bill.created", "fee_bill", bill_id, {"amount_minor": payload["amount_minor"], "currency": payload["currency"]})
        if idempotency_key:
            _save_idempotency(conn, organization_id, "fee_bill.create", idempotency_key, payload, result)
    return result


def list_fee_bills(organization_id: str, student_id: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT b.*, COALESCE((SELECT SUM(a.amount_minor) FROM prototype_fee_payment_allocations a JOIN prototype_fee_payments p ON p.organization_id=a.organization_id AND p.payment_id=a.payment_id WHERE a.organization_id=b.organization_id AND a.bill_id=b.bill_id AND p.status='reconciled'),0) AS paid_minor FROM prototype_fee_bills b WHERE b.organization_id=?"
    args: list[Any] = [organization_id]
    if student_id:
        query += " AND b.student_id=?"
        args.append(student_id)
    query += " ORDER BY b.created_at DESC"
    with db_session() as conn:
        rows = conn.execute(query, args).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["outstanding_minor"] = item["amount_minor"] - item["paid_minor"]
        items.append(item)
    return items


def create_fee_payment(organization_id: str, payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
    """Record a provisional payment once per optional tenant-scoped idempotency key."""
    import uuid
    payment_id = str(uuid.uuid4())
    provisional_ref = "TMP-" + uuid.uuid4().hex[:16].upper()
    with db_session() as conn:
        # Acquire the SQLite write lock before checking the idempotency key.
        # This serializes concurrent retries so only one request can create the record.
        conn.execute("BEGIN IMMEDIATE")
        if idempotency_key:
            replay = _idempotency_replay(conn, organization_id, "fee_payment.create", idempotency_key, payload)
            if replay is not None:
                return replay
        if not conn.execute("SELECT 1 FROM prototype_students WHERE organization_id=? AND student_id=?", (organization_id, payload["student_id"])).fetchone():
            raise LookupError("student")
        allocation_sum = sum(item["amount_minor"] for item in payload["allocations"])
        for allocation in payload["allocations"]:
            bill = conn.execute("SELECT * FROM prototype_fee_bills WHERE organization_id=? AND bill_id=? AND student_id=? AND status='open'", (organization_id, allocation["bill_id"], payload["student_id"])).fetchone()
            if not bill:
                raise LookupError("bill")
            if bill["currency"] != payload["currency"]:
                raise ValueError("Payment currency must match each allocated bill currency")
            posted = conn.execute("SELECT COALESCE(SUM(a.amount_minor),0) FROM prototype_fee_payment_allocations a JOIN prototype_fee_payments p ON p.organization_id=a.organization_id AND p.payment_id=a.payment_id WHERE a.organization_id=? AND a.bill_id=? AND p.status='reconciled'", (organization_id, bill["bill_id"])).fetchone()[0]
            pending = conn.execute("SELECT COALESCE(SUM(a.amount_minor),0) FROM prototype_fee_payment_allocations a JOIN prototype_fee_payments p ON p.organization_id=a.organization_id AND p.payment_id=a.payment_id WHERE a.organization_id=? AND a.bill_id=? AND p.status='pending_reconciliation'", (organization_id, bill["bill_id"])).fetchone()[0]
            if allocation["amount_minor"] > bill["amount_minor"] - posted - pending:
                raise ValueError("Allocation exceeds the bill's remaining unreserved balance")
        conn.execute("INSERT INTO prototype_fee_payments (payment_id, organization_id, student_id, provisional_ref, amount_minor, currency, payment_method, note) VALUES (?,?,?,?,?,?,?,?)", (payment_id, organization_id, payload["student_id"], provisional_ref, payload["amount_minor"], payload["currency"], payload["payment_method"], payload.get("note")))
        for allocation in payload["allocations"]:
            conn.execute("INSERT INTO prototype_fee_payment_allocations (organization_id, payment_id, bill_id, amount_minor) VALUES (?,?,?,?)", (organization_id, payment_id, allocation["bill_id"], allocation["amount_minor"]))
        row = conn.execute("SELECT * FROM prototype_fee_payments WHERE organization_id=? AND payment_id=?", (organization_id, payment_id)).fetchone()
        item = dict(row)
        item["allocated_minor"] = allocation_sum
        item["unallocated_minor"] = payload["amount_minor"] - allocation_sum
        item["official_receipt_number"] = None
        _record_audit_event_conn(conn, organization_id, "finance.payment.recorded", "fee_payment", payment_id, {"amount_minor": payload["amount_minor"], "currency": payload["currency"], "status": row["status"]})
        if idempotency_key:
            _save_idempotency(conn, organization_id, "fee_payment.create", idempotency_key, payload, item)
    return item


def reconcile_fee_payment(organization_id: str, payment_id: str) -> dict[str, Any] | None:
    """Prototype reconciliation: post journal entries once; production requires finance-role authorization."""
    import uuid
    with db_session() as conn:
        payment = conn.execute("SELECT * FROM prototype_fee_payments WHERE organization_id=? AND payment_id=?", (organization_id, payment_id)).fetchone()
        if not payment:
            return None
        if payment["status"] == "reconciled":
            result = dict(payment)
            result["idempotent_replay"] = True
            return result
        if payment["status"] != "pending_reconciliation":
            raise ValueError("Only pending payments can be reconciled")
        allocations = conn.execute("SELECT a.*, b.currency, b.student_id, b.amount_minor AS bill_amount FROM prototype_fee_payment_allocations a JOIN prototype_fee_bills b ON b.organization_id=a.organization_id AND b.bill_id=a.bill_id WHERE a.organization_id=? AND a.payment_id=?", (organization_id, payment_id)).fetchall()
        allocated = sum(row["amount_minor"] for row in allocations)
        for allocation in allocations:
            conn.execute("INSERT INTO prototype_student_account_entries (entry_id, organization_id, student_id, entry_type, amount_minor, currency, bill_id, payment_id) VALUES (?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), organization_id, payment["student_id"], "payment_allocation", -allocation["amount_minor"], payment["currency"], allocation["bill_id"], payment_id))
        credit = payment["amount_minor"] - allocated
        if credit:
            conn.execute("INSERT INTO prototype_student_account_entries (entry_id, organization_id, student_id, entry_type, amount_minor, currency, payment_id) VALUES (?,?,?,?,?,?,?)", (str(uuid.uuid4()), organization_id, payment["student_id"], "student_credit", -credit, payment["currency"], payment_id))
        accounts = _ensure_finance_system_accounts(conn, organization_id, payment["currency"])
        journal_lines = [{"account_id": accounts["1000"], "debit_minor": payment["amount_minor"], "credit_minor": 0}]
        if allocated:
            journal_lines.append({"account_id": accounts["1100"], "debit_minor": 0, "credit_minor": allocated})
        if credit:
            journal_lines.append({"account_id": accounts["2100"], "debit_minor": 0, "credit_minor": credit})
        _post_system_journal(conn, organization_id, f"Reconciled payment {payment['provisional_ref']}", payment["currency"], journal_lines)
        conn.execute("UPDATE prototype_fee_payments SET status='reconciled', reconciled_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE organization_id=? AND payment_id=? AND status='pending_reconciliation'", (organization_id, payment_id))
        row = conn.execute("SELECT * FROM prototype_fee_payments WHERE organization_id=? AND payment_id=?", (organization_id, payment_id)).fetchone()
        _record_audit_event_conn(conn, organization_id, "finance.payment.reconciled", "fee_payment", payment_id, {"amount_minor": payment["amount_minor"], "currency": payment["currency"]})
    return dict(row)


def list_fee_payments(organization_id: str, student_id: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM prototype_fee_payments WHERE organization_id=?"
    args: list[Any] = [organization_id]
    if student_id:
        query += " AND student_id=?"
        args.append(student_id)
    query += " ORDER BY created_at DESC"
    with db_session() as conn:
        rows = conn.execute(query, args).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["allocations"] = [dict(a) for a in conn.execute("SELECT bill_id, amount_minor FROM prototype_fee_payment_allocations WHERE organization_id=? AND payment_id=?", (organization_id, row["payment_id"])).fetchall()]
            output.append(item)
    return output


def student_account_statement(organization_id: str, student_id: str, limit: int = 50, offset: int = 0) -> dict[str, Any] | None:
    """Return a tenant-scoped, paginated fee journal with currency-specific running balances."""
    with db_session() as conn:
        student = conn.execute(
            "SELECT student_id FROM prototype_students WHERE organization_id=? AND student_id=?",
            (organization_id, student_id),
        ).fetchone()
        if not student:
            return None
        total = conn.execute(
            "SELECT COUNT(*) FROM prototype_student_account_entries WHERE organization_id=? AND student_id=?",
            (organization_id, student_id),
        ).fetchone()[0]
        rows = conn.execute("""
            WITH journal AS (
                SELECT e.entry_id, e.student_id, e.entry_type, e.amount_minor, e.currency,
                       e.bill_id, e.payment_id, e.created_at,
                       b.description AS bill_description,
                       p.provisional_ref AS payment_reference,
                       p.status AS payment_status,
                       SUM(e.amount_minor) OVER (
                           PARTITION BY e.currency
                           ORDER BY e.created_at, e.entry_id
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                       ) AS running_balance_minor
                FROM prototype_student_account_entries e
                LEFT JOIN prototype_fee_bills b
                  ON b.organization_id=e.organization_id AND b.bill_id=e.bill_id
                LEFT JOIN prototype_fee_payments p
                  ON p.organization_id=e.organization_id AND p.payment_id=e.payment_id
                WHERE e.organization_id=? AND e.student_id=?
            )
            SELECT * FROM journal
            ORDER BY created_at DESC, entry_id DESC
            LIMIT ? OFFSET ?
        """, (organization_id, student_id, limit, offset)).fetchall()
    return {
        "student_id": student_id,
        "items": [dict(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "prototype_only": True,
    }


def student_account_summary(organization_id: str, student_id: str) -> dict[str, Any] | None:
    with db_session() as conn:
        if not conn.execute("SELECT 1 FROM prototype_students WHERE organization_id=? AND student_id=?", (organization_id, student_id)).fetchone():
            return None
        rows = conn.execute("SELECT currency, SUM(amount_minor) AS balance_minor FROM prototype_student_account_entries WHERE organization_id=? AND student_id=? GROUP BY currency ORDER BY currency", (organization_id, student_id)).fetchall()
        pending = conn.execute("SELECT currency, SUM(amount_minor) AS pending_minor FROM prototype_fee_payments WHERE organization_id=? AND student_id=? AND status='pending_reconciliation' GROUP BY currency", (organization_id, student_id)).fetchall()
    return {"student_id": student_id, "balances": [dict(row) for row in rows], "pending_payments": [dict(row) for row in pending], "prototype_only": True}


def create_ledger_account(organization_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    import uuid
    account_id = str(uuid.uuid4())
    with db_session() as conn:
        conn.execute("INSERT INTO prototype_ledger_accounts (account_id, organization_id, code, name, account_type, currency) VALUES (?, ?, ?, ?, ?, ?)",
                     (account_id, organization_id, payload["code"], payload["name"], payload["account_type"], payload["currency"]))
        row = conn.execute("SELECT * FROM prototype_ledger_accounts WHERE organization_id=? AND account_id=?", (organization_id, account_id)).fetchone()
        _record_audit_event_conn(conn, organization_id, "finance.ledger_account.created", "ledger_account", account_id, {"code": payload["code"], "currency": payload["currency"]})
        return dict(row)


def list_ledger_accounts(organization_id: str) -> list[dict[str, Any]]:
    with db_session() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM prototype_ledger_accounts WHERE organization_id=? ORDER BY code", (organization_id,)).fetchall()]


def post_ledger_journal(organization_id: str, payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
    """Post a balanced journal once per tenant-scoped idempotency key."""
    import uuid
    journal_id = str(uuid.uuid4())
    lines = payload["lines"]
    canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    request_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
    with db_session() as conn:
        # Acquire the SQLite write lock before checking the idempotency key.
        # This serializes concurrent retries so only one request can create the record.
        conn.execute("BEGIN IMMEDIATE")
        if idempotency_key:
            prior = conn.execute(
                "SELECT journal_id, description, currency, request_hash FROM prototype_ledger_journals WHERE organization_id=? AND idempotency_key=?",
                (organization_id, idempotency_key),
            ).fetchone()
            if prior:
                if prior["request_hash"] != request_hash:
                    raise ValueError("Idempotency-Key was already used with a different journal payload")
                result = _ledger_journal_result(conn, organization_id, prior["journal_id"])
                result["idempotent_replay"] = True
                return result
        accounts = {}
        for line in lines:
            account = conn.execute("SELECT account_id, currency, status FROM prototype_ledger_accounts WHERE organization_id=? AND account_id=?", (organization_id, line["account_id"])).fetchone()
            if account is None:
                raise LookupError("account")
            if account["status"] != "active":
                raise ValueError("Inactive ledger accounts cannot receive postings")
            if account["currency"] != payload["currency"]:
                raise ValueError("Journal currency must match every account currency")
            accounts[line["account_id"]] = account
        debits = sum(line["debit_minor"] for line in lines)
        credits = sum(line["credit_minor"] for line in lines)
        if debits != credits or debits <= 0:
            raise ValueError("Journal entry must be balanced and non-zero")
        conn.execute("INSERT INTO prototype_ledger_journals (journal_id, organization_id, description, currency, idempotency_key, request_hash, reversal_of_id) VALUES (?, ?, ?, ?, ?, ?, NULL)",
                     (journal_id, organization_id, payload["description"], payload["currency"], idempotency_key, request_hash if idempotency_key else None))
        for index, line in enumerate(lines, start=1):
            conn.execute("INSERT INTO prototype_ledger_lines (organization_id, journal_id, line_number, account_id, debit_minor, credit_minor) VALUES (?, ?, ?, ?, ?, ?)",
                         (organization_id, journal_id, index, line["account_id"], line["debit_minor"], line["credit_minor"]))
        _record_audit_event_conn(conn, organization_id, "finance.ledger_journal.posted", "ledger_journal", journal_id, {"currency": payload["currency"], "total_debit_minor": debits, "line_count": len(lines)})
        return {"journal_id": journal_id, "organization_id": organization_id, "description": payload["description"], "currency": payload["currency"], "status": "posted", "total_debit_minor": debits, "total_credit_minor": credits, "lines": lines, "idempotent_replay": False}


def reverse_ledger_journal(organization_id: str, journal_id: str, reason: str) -> dict[str, Any] | None:
    """Append an exact, tenant-scoped reversal; never mutate the posted original."""
    import uuid
    reason = reason.strip()
    if not reason:
        raise ValueError("A reversal reason is required")
    with db_session() as conn:
        original = conn.execute(
            "SELECT journal_id, description, currency, reversal_of_id FROM prototype_ledger_journals WHERE organization_id=? AND journal_id=?",
            (organization_id, journal_id),
        ).fetchone()
        if original is None:
            return None
        if original["reversal_of_id"] is not None:
            raise ValueError("A reversal journal cannot itself be reversed; reverse the original journal only")
        prior = conn.execute(
            "SELECT journal_id FROM prototype_ledger_journals WHERE organization_id=? AND reversal_of_id=?",
            (organization_id, journal_id),
        ).fetchone()
        if prior:
            raise ValueError(f"Journal has already been reversed by {prior['journal_id']}")
        lines = conn.execute(
            "SELECT account_id, debit_minor, credit_minor FROM prototype_ledger_lines WHERE organization_id=? AND journal_id=? ORDER BY line_number",
            (organization_id, journal_id),
        ).fetchall()
        reversal_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO prototype_ledger_journals (journal_id, organization_id, description, currency, reversal_of_id) VALUES (?, ?, ?, ?, ?)",
            (reversal_id, organization_id, f"Reversal of {journal_id}: {reason}"[:240], original["currency"], journal_id),
        )
        for index, line in enumerate(lines, start=1):
            conn.execute(
                "INSERT INTO prototype_ledger_lines (organization_id, journal_id, line_number, account_id, debit_minor, credit_minor) VALUES (?, ?, ?, ?, ?, ?)",
                (organization_id, reversal_id, index, line["account_id"], line["credit_minor"], line["debit_minor"]),
            )
        result = _ledger_journal_result(conn, organization_id, reversal_id)
        result["reversal_of_id"] = journal_id
        _record_audit_event_conn(conn, organization_id, "finance.ledger_journal.reversed", "ledger_journal", reversal_id, {"reversal_of_id": journal_id, "currency": result["currency"], "reason": reason})
        return result


def _ledger_journal_result(conn: sqlite3.Connection, organization_id: str, journal_id: str) -> dict[str, Any]:
    journal = conn.execute(
        "SELECT journal_id, organization_id, description, currency, status, reversal_of_id FROM prototype_ledger_journals WHERE organization_id=? AND journal_id=?",
        (organization_id, journal_id),
    ).fetchone()
    lines = [dict(row) for row in conn.execute(
        "SELECT l.line_number, l.account_id, a.code AS account_code, a.name AS account_name, l.debit_minor, l.credit_minor "
        "FROM prototype_ledger_lines l JOIN prototype_ledger_accounts a ON a.organization_id=l.organization_id AND a.account_id=l.account_id "
        "WHERE l.organization_id=? AND l.journal_id=? ORDER BY l.line_number", (organization_id, journal_id)
    ).fetchall()]
    result = dict(journal)
    result["lines"] = lines
    result["total_debit_minor"] = sum(line["debit_minor"] for line in lines)
    result["total_credit_minor"] = sum(line["credit_minor"] for line in lines)
    return result


def list_ledger_journals(organization_id: str, currency: str = "ETB", account_id: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """List posted journals with their lines, scoped to an organization and currency."""
    with db_session() as conn:
        where = ["j.organization_id=?", "j.currency=?"]
        args: list[Any] = [organization_id, currency]
        if account_id:
            exists = conn.execute(
                "SELECT 1 FROM prototype_ledger_accounts WHERE organization_id=? AND account_id=?",
                (organization_id, account_id),
            ).fetchone()
            if exists is None:
                raise LookupError("account")
            where.append("EXISTS (SELECT 1 FROM prototype_ledger_lines fx WHERE fx.organization_id=j.organization_id AND fx.journal_id=j.journal_id AND fx.account_id=?)")
            args.append(account_id)
        predicate = " AND ".join(where)
        total = conn.execute(f"SELECT COUNT(*) FROM prototype_ledger_journals j WHERE {predicate}", args).fetchone()[0]
        journals = conn.execute(
            f"SELECT j.journal_id, j.organization_id, j.description, j.currency, j.status, j.created_at, j.reversal_of_id, "
            f"(SELECT r.journal_id FROM prototype_ledger_journals r WHERE r.organization_id=j.organization_id AND r.reversal_of_id=j.journal_id LIMIT 1) AS reversed_by_id, "
            f"(SELECT COALESCE(SUM(l.debit_minor),0) FROM prototype_ledger_lines l WHERE l.organization_id=j.organization_id AND l.journal_id=j.journal_id) AS total_debit_minor, "
            f"(SELECT COALESCE(SUM(l.credit_minor),0) FROM prototype_ledger_lines l WHERE l.organization_id=j.organization_id AND l.journal_id=j.journal_id) AS total_credit_minor "
            f"FROM prototype_ledger_journals j WHERE {predicate} ORDER BY j.created_at DESC, j.journal_id DESC LIMIT ? OFFSET ?",
            [*args, limit, offset],
        ).fetchall()
        items = []
        for journal in journals:
            item = dict(journal)
            item["lines"] = [dict(line) for line in conn.execute(
                "SELECT l.line_number, l.account_id, a.code AS account_code, a.name AS account_name, l.debit_minor, l.credit_minor "
                "FROM prototype_ledger_lines l JOIN prototype_ledger_accounts a ON a.organization_id=l.organization_id AND a.account_id=l.account_id "
                "WHERE l.organization_id=? AND l.journal_id=? ORDER BY l.line_number",
                (organization_id, journal["journal_id"]),
            ).fetchall()]
            items.append(item)
        return {"items": items, "total": total, "limit": limit, "offset": offset, "currency": currency}


def ledger_account_activity(organization_id: str, account_id: str, limit: int = 50, offset: int = 0) -> dict[str, Any] | None:
    """Return a tenant-scoped account ledger with a stable running net-debit balance."""
    with db_session() as conn:
        account = conn.execute(
            "SELECT account_id, organization_id, code, name, account_type, currency, status "
            "FROM prototype_ledger_accounts WHERE organization_id=? AND account_id=?",
            (organization_id, account_id),
        ).fetchone()
        if account is None:
            return None
        rows = conn.execute(
            "SELECT j.journal_id, j.description, j.currency, j.created_at, l.line_number, l.debit_minor, l.credit_minor "
            "FROM prototype_ledger_lines l JOIN prototype_ledger_journals j "
            "ON j.organization_id=l.organization_id AND j.journal_id=l.journal_id "
            "WHERE l.organization_id=? AND l.account_id=? ORDER BY j.created_at, j.journal_id, l.line_number",
            (organization_id, account_id),
        ).fetchall()
        running = 0
        entries = []
        total_debit = total_credit = 0
        for row in rows:
            item = dict(row)
            running += item["debit_minor"] - item["credit_minor"]
            item["running_net_debit_minor"] = running
            total_debit += item["debit_minor"]
            total_credit += item["credit_minor"]
            entries.append(item)
        return {
            "account": dict(account), "items": entries[offset:offset + limit], "total": len(entries),
            "limit": limit, "offset": offset, "total_debit_minor": total_debit,
            "total_credit_minor": total_credit, "closing_net_debit_minor": running,
        }


def ledger_trial_balance(organization_id: str, currency: str = "ETB") -> dict[str, Any]:
    with db_session() as conn:
        rows = conn.execute("""
            SELECT a.account_id, a.code, a.name, a.account_type, a.currency,
                   COALESCE(SUM(l.debit_minor), 0) AS debit_minor,
                   COALESCE(SUM(l.credit_minor), 0) AS credit_minor
            FROM prototype_ledger_accounts a
            LEFT JOIN prototype_ledger_lines l ON l.organization_id=a.organization_id AND l.account_id=a.account_id
            LEFT JOIN prototype_ledger_journals j ON j.organization_id=l.organization_id AND j.journal_id=l.journal_id AND j.currency=a.currency
            WHERE a.organization_id=? AND a.currency=?
            GROUP BY a.account_id ORDER BY a.code
        """, (organization_id, currency)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["net_debit_minor"] = item["debit_minor"] - item["credit_minor"]
            items.append(item)
        total_debit = sum(item["debit_minor"] for item in items)
        total_credit = sum(item["credit_minor"] for item in items)
        return {"currency": currency, "items": items, "total_debit_minor": total_debit, "total_credit_minor": total_credit, "is_balanced": total_debit == total_credit}
