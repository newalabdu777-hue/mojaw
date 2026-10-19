# Backend API foundation (non-production)

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/api/v1/docs` for the API contract.

## Run tests

```powershell
python -m unittest discover -s tests -v
```

## Current scope

- Configurable runtime settings and explicit CORS allowlist
- Liveness and readiness probes
- Versioned OpenAPI documentation route
- Initial student request/response DTO contract with strict validation
- Automated foundation tests

## Scope and limitations

Authentication/authorization, approved production persistence, trusted tenant enforcement, sync/outbox, financial posting, official numbering, and production migrations are not implemented. Student and classroom records use a disposable local SQLite prototype. Do not use this starter for real student data or production deployment.

## Student API (development prototype)

All student endpoints require `X-Organization-ID`. This header is a prototype tenant selector, **not authentication or authorization**.

- `GET /api/v1/students?limit=50&offset=0` — list students, optionally filtered by `branch_id`.
- `POST /api/v1/students` — create a student record.
- `GET /api/v1/students/{student_id}` — fetch a student within the selected organization.
- `PATCH /api/v1/students/{student_id}` — update editable student details. `branch_id` is intentionally not editable here; transfers need a separate audited workflow.

Data is stored in a disposable local SQLite development database. Do not use real student data. These endpoints are not production-ready until authentication, authorization, approved schema, audit policy, migrations, and deployment controls are implemented.

## Tests

From this `backend` directory, run:

```bash
python -m pytest -q
```

## Attendance endpoints (prototype)

- `POST /api/v1/attendance`
- `GET /api/v1/attendance`
- `PATCH /api/v1/attendance/{attendance_id}` (correction reason required)
- `GET /api/v1/attendance/{attendance_id}/history`

A unique constraint prevents duplicate student/date attendance records per organization. Corrections are logged with the prior status, new status, reason, and timestamp. This is prototype-only and the organization header is not an authenticated identity. Do not use real personal data.

Run tests from this directory with `python -m pytest -q`.


## Classroom structure API (prototype)

- `POST/GET /api/v1/classrooms/academic-years`
- `POST/GET /api/v1/classrooms/class-levels`
- `POST/GET /api/v1/classrooms/sections`
- `POST/GET /api/v1/classrooms/enrollments`

Enrollment creation checks organization scope, student/section branch match, active student/section status, section capacity, and one active enrollment per student per organization. Lifecycle operations and production authorization are not yet implemented. Run `python -m pytest -q` to exercise the current API suite.


## Finance and audit API (prototype)

The development-only finance routes include bills, provisional payments, reconciliation, student-account summaries, double-entry ledger accounts/journals, journal reversals, trial balance, and `GET /api/v1/finance/audit-events`. Audit events can be filtered by `entity_type`, `entity_id`, and `event_type` and paginated with `limit`/`offset`. Local SQLite triggers reject audit-row updates/deletes. Events currently cover bill creation, payment recording/reconciliation, ledger-account creation, journal posting, and journal reversal.

This audit layer is **not production-grade yet**: actor identity is unavailable until authentication is implemented, audit writes are not committed atomically with business changes, and SQLite triggers do not protect against a database administrator. `X-Organization-ID` is caller-controlled and is not authorization. Never use real student or finance data.

## Local SQLite backup utility (development only)

The helper uses SQLite's online backup API (so it also handles an active WAL database), writes to a temporary file, and verifies SQLite integrity plus foreign-key consistency before publishing the backup. It rejects destination symlinks, avoids overwriting an existing backup unless `--overwrite` is explicitly provided, and uses no-clobber publication when creating a new backup. Tests cover snapshot isolation and corrupt database detection.

```powershell
# From the backend directory; default source follows SCHOOL_DEV_DB_PATH
python scripts/sqlite_backup.py backup .\backups\school-dev.sqlite3
python scripts/sqlite_backup.py verify .\backups\school-dev.sqlite3

# Explicit source, and only if you intentionally want to replace an existing backup:
python scripts/sqlite_backup.py backup .\backups\school-dev.sqlite3 --source .\.dev_students.sqlite3 --overwrite
```

Keep backups encrypted and access-controlled, and test restores. This utility is not a production backup/restore system, does not upload offsite copies, and does not establish an RPO/RTO guarantee. The prototype database must not contain real student or financial data.

Run backup tests with `python -m pytest tests/test_sqlite_backup.py -q` from this directory. A successful integrity check is not a substitute for a scheduled restore drill: verify that the application can start and expected records can be read from a restored copy before depending on a backup.

### Offline sync API prototype

`POST /api/v1/sync/batch` currently supports `student_profile` create/update, `attendance_record` create/update, and `draft_assessment_result` create/update mutations. Creates start at entity version 1; updates require `base_version`, apply only when it matches the current version, increment the version only when data changes, and append an audit/history entry. The domain change, history entry, and idempotency outcome are written in one SQLite transaction. Exact retries return `duplicate`; stale versions return `conflict`; deletes and unsupported entities are rejected. The browser queue transport and manual sync panel exist. Attendance create forms and draft assessment score submissions can enqueue offline mutations; score queuing requires the assessment and student roster to have been loaded before the device goes offline. Pending queued scores are restored over fetched server results after reload when the API is reachable; conflicts are not silently overlaid. Assessment creation and offline roster caching are not supported. This is still a development-only prototype: production authorization/persistence, retention, and full end-to-end offline sync remain incomplete. Do not use real student or finance data.
