"""Prototype authentication primitives. Not a substitute for an audited production IAM system."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from typing import Any
from uuid import uuid4
from app.services.student_store import db_session

PBKDF2_ITERATIONS = 310_000
TOKEN_TTL_SECONDS = 15 * 60
LOGIN_FAILURE_LIMIT = 10
LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
ALLOWED_ROLES = {"organization_admin", "branch_admin", "registrar", "teacher", "cashier", "finance_manager", "viewer"}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64(salt)}${_b64(digest)}"


DUMMY_PASSWORD_HASH = hash_password("dummy-password-never-used-for-login")


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _unb64(salt), int(iterations))
        return hmac.compare_digest(actual, _unb64(expected))
    except (ValueError, TypeError):
        return False


def _secret() -> bytes:
    secret = os.environ.get("SCHOOL_AUTH_SECRET", "")
    if len(secret.encode("utf-8")) < 32:
        raise RuntimeError("SCHOOL_AUTH_SECRET must contain at least 32 bytes when authentication is enabled")
    return secret.encode("utf-8")


def create_access_token(user: dict[str, Any], secret: bytes | None = None, now: int | None = None) -> str:
    secret = secret or _secret()
    now = int(time.time()) if now is None else now
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": user["user_id"], "org": user["organization_id"], "role": user["role"], "iat": now, "exp": now + TOKEN_TTL_SECONDS, "jti": str(uuid4())}
    unsigned = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}.{_b64(json.dumps(payload, separators=(',', ':')).encode())}"
    return f"{unsigned}.{_b64(hmac.new(secret, unsigned.encode(), hashlib.sha256).digest())}"


def verify_access_token(token: str, secret: bytes | None = None, now: int | None = None) -> dict[str, Any]:
    secret = secret or _secret()
    try:
        header_part, payload_part, signature_part = token.split(".")
        unsigned = f"{header_part}.{payload_part}"
        expected = hmac.new(secret, unsigned.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(signature_part)):
            raise ValueError("invalid signature")
        header = json.loads(_unb64(header_part))
        payload = json.loads(_unb64(payload_part))
        current = int(time.time()) if now is None else now
        if header != {"alg": "HS256", "typ": "JWT"} or not isinstance(payload.get("exp"), int) or payload["exp"] <= current:
            raise ValueError("invalid or expired token")
        if not all(isinstance(payload.get(k), str) and payload[k] for k in ("sub", "org", "role")):
            raise ValueError("invalid claims")
        if payload["role"] not in ALLOWED_ROLES:
            raise ValueError("invalid role")
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid or expired access token") from exc


def ensure_auth_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS prototype_users (
        user_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, email TEXT NOT NULL COLLATE NOCASE,
        password_hash TEXT NOT NULL, role TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE (organization_id, email))""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_proto_users_org_active ON prototype_users(organization_id, is_active)")


def ensure_login_attempt_table(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS prototype_login_attempts (
        organization_id TEXT NOT NULL, email TEXT NOT NULL COLLATE NOCASE,
        window_started_at INTEGER NOT NULL, failure_count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (organization_id, email))""")


def login_block_seconds(organization_id: str, email: str, now: int | None = None) -> int:
    """Return remaining cooldown seconds for a normalized organization/email pair."""
    current = int(time.time()) if now is None else now
    with db_session() as conn:
        ensure_login_attempt_table(conn)
        row = conn.execute(
            "SELECT window_started_at, failure_count FROM prototype_login_attempts WHERE organization_id=? AND email=?",
            (organization_id.strip(), email.strip().lower()),
        ).fetchone()
        if row is None or row["failure_count"] < LOGIN_FAILURE_LIMIT:
            return 0
        elapsed = current - int(row["window_started_at"])
        # Wall-clock adjustments must not produce a cooldown longer than the configured window.
        remaining = LOGIN_FAILURE_WINDOW_SECONDS - max(0, elapsed)
        if elapsed >= LOGIN_FAILURE_WINDOW_SECONDS:
            conn.execute("DELETE FROM prototype_login_attempts WHERE organization_id=? AND email=?", (organization_id.strip(), email.strip().lower()))
            return 0
        return remaining


def record_login_failure(organization_id: str, email: str, now: int | None = None) -> int:
    """Atomically record a failed login and return the current cooldown in seconds."""
    current = int(time.time()) if now is None else now
    organization_id, email = organization_id.strip(), email.strip().lower()
    with db_session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure_login_attempt_table(conn)
        row = conn.execute(
            "SELECT window_started_at, failure_count FROM prototype_login_attempts WHERE organization_id=? AND email=?",
            (organization_id, email),
        ).fetchone()
        if row is None or current - int(row["window_started_at"]) >= LOGIN_FAILURE_WINDOW_SECONDS:
            started, failures = current, 1
            conn.execute(
                "INSERT INTO prototype_login_attempts(organization_id,email,window_started_at,failure_count) VALUES (?,?,?,?) "
                "ON CONFLICT(organization_id,email) DO UPDATE SET window_started_at=excluded.window_started_at,failure_count=excluded.failure_count",
                (organization_id, email, started, failures),
            )
        else:
            started, failures = int(row["window_started_at"]), int(row["failure_count"]) + 1
            conn.execute("UPDATE prototype_login_attempts SET failure_count=? WHERE organization_id=? AND email=?", (failures, organization_id, email))
        elapsed = max(0, current - started)
        return max(0, LOGIN_FAILURE_WINDOW_SECONDS - elapsed) if failures >= LOGIN_FAILURE_LIMIT else 0


def clear_login_failures(organization_id: str, email: str) -> None:
    with db_session() as conn:
        ensure_login_attempt_table(conn)
        conn.execute("DELETE FROM prototype_login_attempts WHERE organization_id=? AND email=?", (organization_id.strip(), email.strip().lower()))


def user_by_email(organization_id: str, email: str) -> dict[str, Any] | None:
    with db_session() as conn:
        ensure_auth_tables(conn)
        row = conn.execute("SELECT * FROM prototype_users WHERE organization_id=? AND email=?", (organization_id, email.strip().lower())).fetchone()
        return dict(row) if row else None


def user_by_id(user_id: str, organization_id: str) -> dict[str, Any] | None:
    with db_session() as conn:
        ensure_auth_tables(conn)
        row = conn.execute("SELECT user_id, organization_id, email, role, is_active, created_at FROM prototype_users WHERE user_id=? AND organization_id=?", (user_id, organization_id)).fetchone()
        return dict(row) if row else None


def count_users(organization_id: str | None = None) -> int:
    with db_session() as conn:
        ensure_auth_tables(conn)
        if organization_id is None:
            return int(conn.execute("SELECT COUNT(*) FROM prototype_users").fetchone()[0])
        return int(conn.execute("SELECT COUNT(*) FROM prototype_users WHERE organization_id=?", (organization_id,)).fetchone()[0])


def create_user(organization_id: str, email: str, password: str, role: str) -> dict[str, Any]:
    if role not in ALLOWED_ROLES:
        raise ValueError("Unsupported role")
    email = email.strip().lower()
    if len(email) > 254 or "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ValueError("A valid email address is required")
    if len(password) < 12 or len(password) > 128:
        raise ValueError("Password must be between 12 and 128 characters")
    user_id = str(uuid4())
    with db_session() as conn:
        ensure_auth_tables(conn)
        conn.execute("INSERT INTO prototype_users(user_id, organization_id, email, password_hash, role) VALUES (?,?,?,?,?)", (user_id, organization_id, email, hash_password(password), role))
        row = conn.execute("SELECT user_id, organization_id, email, role, is_active, created_at FROM prototype_users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row)


def authenticate(organization_id: str, email: str, password: str) -> dict[str, Any] | None:
    user = user_by_email(organization_id, email)
    # Constant-ish work for unknown email to reduce obvious timing differences.
    if user is None:
        verify_password(password, DUMMY_PASSWORD_HASH)
        return None
    if not user["is_active"] or not verify_password(password, user["password_hash"]):
        return None
    return {k: user[k] for k in ("user_id", "organization_id", "email", "role", "is_active", "created_at")}


def list_users(organization_id: str, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    with db_session() as conn:
        ensure_auth_tables(conn)
        total = conn.execute("SELECT COUNT(*) FROM prototype_users WHERE organization_id=?", (organization_id,)).fetchone()[0]
        rows = conn.execute("SELECT user_id, organization_id, email, role, is_active, created_at FROM prototype_users WHERE organization_id=? ORDER BY email LIMIT ? OFFSET ?", (organization_id, limit, offset)).fetchall()
        return {"items": [dict(row) for row in rows], "total": int(total), "limit": limit, "offset": offset}


def create_first_admin(organization_id: str, email: str, password: str) -> dict[str, Any]:
    """Atomically create the first organization admin; concurrent bootstrap calls cannot both win."""
    email = email.strip().lower()
    if len(organization_id.strip()) > 64 or not organization_id.strip():
        raise ValueError("A valid organization ID is required")
    if len(email) > 254 or "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ValueError("A valid email address is required")
    if len(password) < 12 or len(password) > 128:
        raise ValueError("Password must be between 12 and 128 characters")
    user_id = str(uuid4())
    with db_session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure_auth_tables(conn)
        if conn.execute("SELECT 1 FROM prototype_users WHERE organization_id=? LIMIT 1", (organization_id.strip(),)).fetchone():
            raise RuntimeError("Bootstrap is already closed for this organization")
        conn.execute("INSERT INTO prototype_users(user_id, organization_id, email, password_hash, role) VALUES (?,?,?,?,?)", (user_id, organization_id.strip(), email, hash_password(password), "organization_admin"))
        row = conn.execute("SELECT user_id, organization_id, email, role, is_active, created_at FROM prototype_users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row)


def role_allows(role: str, method: str, path: str) -> bool:
    """Conservative prototype endpoint policy. Branch and record-level scoping remain unimplemented."""
    import re

    method = method.upper()
    if role == "organization_admin":
        return True
    if path.startswith("/api/v1/auth/users"):
        return False
    if role == "viewer":
        return method in {"GET", "HEAD"}
    if role == "branch_admin":
        # Fail closed until branch assignments and row-level branch scoping are implemented.
        return False

    # Use route-shaped allowlists rather than substring checks. This deliberately denies
    # unknown/future endpoints until a policy is explicitly added here.
    if role == "registrar":
        if path in {"/api/v1/students", "/api/v1/classrooms/academic-years",
                    "/api/v1/classrooms/class-levels", "/api/v1/classrooms/sections",
                    "/api/v1/classrooms/enrollments"}:
            return method in {"GET", "POST"}
        if path == "/api/v1/guardians":
            return method == "GET"
        if re.fullmatch(r"/api/v1/students/[^/]+", path):
            return method in {"GET", "PATCH"}
        if re.fullmatch(r"/api/v1/students/[^/]+/history", path):
            return method == "GET"
        if re.fullmatch(r"/api/v1/students/[^/]+/guardians", path):
            return method in {"GET", "POST"}
        if re.fullmatch(r"/api/v1/students/[^/]+/guardians/[^/]+/link", path):
            return method == "POST"
        if path.startswith("/api/v1/academics/"):
            return method == "GET"
        if path.startswith("/api/v1/classrooms/"):
            return method == "GET"
        return False

    if role == "teacher":
        if path == "/api/v1/attendance":
            return method in {"GET", "POST"}
        if path == "/api/v1/attendance/bulk" or re.fullmatch(r"/api/v1/attendance/sections/[^/]+/bulk", path):
            return method == "POST"
        if path.startswith("/api/v1/attendance/reports/") or path in {"/api/v1/attendance/summary"}:
            return method == "GET"
        if re.fullmatch(r"/api/v1/attendance/[^/]+", path):
            return method in {"GET", "PATCH"}
        if re.fullmatch(r"/api/v1/attendance/[^/]+/history", path):
            return method == "GET"
        if path.startswith("/api/v1/academics/"):
            if method == "GET":
                return True
            return method == "POST" and re.fullmatch(r"/api/v1/academics/assessments/[^/]+/results", path) is not None
        if path.startswith("/api/v1/classrooms/"):
            return method == "GET"
        return False

    if role == "cashier":
        if path.startswith("/api/v1/students"):
            return method == "GET"
        if path in {"/api/v1/finance/bills", "/api/v1/finance/payments"}:
            return method == "GET" or (path.endswith("/payments") and method == "POST")
        if re.fullmatch(r"/api/v1/finance/students/[^/]+/(account|statement)", path):
            return method == "GET"
        return False

    if role == "finance_manager":
        if path.startswith("/api/v1/students"):
            return method == "GET"
        if path.startswith("/api/v1/finance/") or path == "/api/v1/finance":
            if method == "GET":
                return True
            # Posting is permitted, but journal reversal is excluded until dual approval exists.
            if method == "POST":
                return path in {"/api/v1/finance/bills", "/api/v1/finance/payments",
                                "/api/v1/finance/ledger/accounts", "/api/v1/finance/ledger/journals"}
            return False
        return False
    return False
