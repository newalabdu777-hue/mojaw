# School Management System — Development Prototype


> **Production startup guard:** this starter API deliberately refuses to start when `SCHOOL_ENVIRONMENT=production` (or `prod`). It is not safe for real student or financial data until authentication/authorization, approved production persistence and migrations, and operational controls are implemented. Keep it in development/test environments only.

A non-production starter for a multi-branch school management system, with an English/Amharic React interface and a FastAPI backend. The backend includes disposable local SQLite prototypes for student records, attendance, assessments/results, academic years, class levels, sections, and enrollments. Several frontend modules remain demonstrations or placeholders.

## Frontend

```powershell
cd frontend
npm install
npm test
npm run build
npm run dev
```

## Prototype authentication and role enforcement (new)

The API now includes a development/staging authentication layer. It is **opt-in** so existing local demo flows remain compatible; set `SCHOOL_AUTH_REQUIRED=true` to enforce bearer authentication on `/api/v1/*` domain routes. When enabled, configure `SCHOOL_AUTH_SECRET` to a random secret of at least 32 bytes. Production startup remains blocked intentionally. This implementation is a prototype and has not undergone an external security review.

1. Set `SCHOOL_AUTH_SECRET` to a strong random secret (for example, generate one with your operating system's cryptographic random generator).
2. Set `SCHOOL_BOOTSTRAP_TOKEN` to a separate random secret of at least 32 bytes.
3. Start the API in development only, then create the first administrator for an organization using the bootstrap token:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/bootstrap-admin \
  -H 'Content-Type: application/json' \
  -H 'X-Bootstrap-Token: replace-with-your-bootstrap-token' \
  -d '{"organization_id":"demo-school","email":"admin@example.com","password":"Use-A-Unique-Long-Password-Here-9!"}'
```

4. Remove `SCHOOL_BOOTSTRAP_TOKEN` from the environment after creating the administrator. Log in at `POST /api/v1/auth/login` with `organization_id`, `email`, and `password`; send the returned short-lived token as `Authorization: Bearer <token>`. Use `GET /api/v1/auth/me` to check the current identity. Organization administrators can list and create users at `/api/v1/auth/users`. Passwords are stored using PBKDF2-HMAC-SHA256, and access tokens are HMAC-signed and expire after 15 minutes. Login attempts are counted per organization/email; 10 failures in a 15-minute window trigger a temporary 429 response with `Retry-After`, and a successful login clears that counter. This is a local prototype throttle, not distributed/IP-based abuse protection.

### Frontend sign-in (prototype)

Set `VITE_AUTH_ENABLED=true` in the frontend environment and set `SCHOOL_AUTH_REQUIRED=true` in the backend environment. Configure `VITE_API_BASE_URL` and `VITE_DEMO_ORGANIZATION_ID` to match your local API and organization. The UI then displays a sign-in screen, attaches the bearer token to API requests, loads the current identity from `/api/v1/auth/me`, displays the authenticated email and role in the profile area, clears the tab-scoped token on a 401 response, and offers sign-out. The token is kept in `sessionStorage` for this prototype; this is not a substitute for a reviewed production session design. Keep credentials and real records out of demo deployments.

Roles currently supported: `organization_admin`, `branch_admin`, `registrar`, `teacher`, `cashier`, `finance_manager`, and `viewer`. The API applies conservative route/method allowlists; unknown routes are denied for non-admin roles, `branch_admin` is denied domain-route access until branch assignments and row scoping exist, and finance managers cannot reverse journals through this role policy until dual approval exists. In authenticated mode, the verified token's organization ID is injected as `X-Organization-ID` when the caller omits it; a conflicting supplied organization ID is rejected. This reduces accidental tenant mismatch but does not replace reviewed tenant isolation. These checks are still endpoint-level only: **branch-level row scoping, distributed/IP-based abuse protection, refresh/revocation sessions, MFA, secure email verification, and audited actor attribution remain incomplete. A basic organization/email login cooldown is present for prototype testing, but is not sufficient for production.** This is not a production IAM system. Keep `SCHOOL_AUTH_REQUIRED=false` only for isolated local demos; never expose this prototype to a public network or use real personal/financial data.


## Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API docs: `http://127.0.0.1:8000/api/v1/docs`

Open the frontend at the Vite URL (normally `http://localhost:5173`) and select **Students**, **Classes & enrollment**, **Attendance**, or **Academics** to exercise the development API-backed workflows. The frontend defaults to `http://127.0.0.1:8000`; optionally set `VITE_API_BASE_URL` and `VITE_DEMO_ORGANIZATION_ID` in a frontend `.env` file. The default organization ID is `demo-organization`.

Run backend tests from `backend` with `PYTHONPATH=. pytest -q` (install dependencies from `requirements.txt` first).

## Student API prototype

All student endpoints require an `X-Organization-ID` header. This is only a development filter, **not authentication or a security boundary**.

Create a student:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/students \
  -H 'Content-Type: application/json' \
  -H 'X-Organization-ID: demo-school' \
  -d '{"given_name":"Mimi","family_name":"Abebe","branch_id":"main"}'
```

List students:

```bash
curl http://127.0.0.1:8000/api/v1/students -H 'X-Organization-ID: demo-school'
```

Student history and deactivation:

```bash
# Read a student's audit events (bounded pagination: limit 1–200)
curl 'http://127.0.0.1:8000/api/v1/students/STUDENT_ID/history?limit=50&offset=0' \
  -H 'X-Organization-ID: demo-school'

# Deactivate without deleting the record; a reason is required
curl -X POST 'http://127.0.0.1:8000/api/v1/students/STUDENT_ID/deactivate' \
  -H 'Content-Type: application/json' -H 'X-Organization-ID: demo-school' \
  -d '{"reason":"Left the school"}'
```

The history endpoint verifies tenant-scoped student existence before returning events. The deactivation and its audit event are committed in one database transaction. Repeating deactivation returns `409`; audit events are append-only in this prototype. These protections do not replace real authentication/authorization. The student directory UI now exposes a bilingual History panel and a reason-required Deactivate form; deactivated students remain in the directory and the history panel renders recorded audit event details. The frontend build still needs verification in an environment with its npm dependencies installed.

The local database defaults to `backend/.dev_students.sqlite3`. Set `SCHOOL_DEV_DB_PATH` to use a different location, including a temporary test database.

## Important safety and scope

- This is a **development prototype, not a complete or production-ready school system**.
- The student store is a temporary SQLite prototype, not the approved final schema. It does not allocate official admission numbers.
- Dashboard figures remain mock data. Students, Classes & enrollment, Attendance, Assessments, and the Finance prototype use development APIs; Reports and Settings remain placeholders.
- A prototype authentication/role layer now exists but is opt-in and not production-grade; granular authorization, production-grade tenant isolation, PostgreSQL persistence, financial approvals, offline sync/outbox, and backup/recovery are not implemented. The Finance prototype includes local double-entry ledger posting but is not a production accounting system.
- Do not enter real student, guardian, staff, or financial information. The organization header is caller-controlled and must never be treated as proof of access.
- Production migrations remain on hold until the consolidated final schema is explicitly approved.

## Next implementation stages

1. Approve the consolidated schema and close unresolved decisions.
2. Harden the prototype authentication into reviewed production IAM and complete server-enforced organization/branch assignments.
3. Replace prototype SQLite storage with the approved PostgreSQL schema and migration path.
4. Complete enrollment/guardian workflows, class-aware attendance and assessment selection, and production-grade audit events.
5. Complete academic workflows using section enrollments, grading scales, approvals, immutable result revisions, and report cards.
6. Harden the finance prototype with approvals, trusted actor identity, atomic business/audit writes, official numbering, and reconciliation.
7. Implement durable offline outbox, idempotent sync, conflicts, and tested recovery.

### Student record updates

The development API now supports `PATCH /api/v1/students/{student_id}` for editable personal details. Branch changes are intentionally excluded from this endpoint so that future transfers can use a separate audited workflow. This remains a local prototype and requires `X-Organization-ID`, which is not an authentication mechanism.

## Latest development increment: student guardians

The development-only FastAPI prototype now includes guardian-link endpoints:

- `GET /api/v1/students/{student_id}/guardians`
- `POST /api/v1/students/{student_id}/guardians`

Supply `X-Organization-ID` on requests. This header is only a development tenant selector; it is **not authentication or authorization**. Guardian portal access defaults to disabled and is not granted by marking a guardian primary. The prototype creates a separate guardian identity for each POST; cross-student shared guardian identity and deduplication are not implemented yet. Do not store real personal data in this prototype.

Run backend tests from `backend/` with `python -m unittest discover -s tests -v`. The current suite has since grown; use `python -m pytest -q` for the current result.

Production migrations remain on hold pending explicit approval of the consolidated final schema.

### Guardian management UI (development prototype)

The Students screen now provides a **Guardians** action on each student row. It loads that student's linked guardians and offers a form to add a guardian through the development API. This screen has not been frontend-build-verified in this environment because npm dependencies are not installed. The backend suite was run and passed (15 tests). Shared guardian identity across multiple students is still not implemented, and the caller-controlled organization header is not a security boundary.

## Attendance API (development prototype)

The backend includes attendance endpoints backed by the disposable development SQLite database:

- `POST /api/v1/attendance` — record one student's status for a date (`present`, `absent`, `late`, `excused`).
- `POST /api/v1/attendance/bulk` — record up to 500 students for one date in a single atomic operation. The request is rejected if it contains duplicate student IDs, any student does not belong to the organization, or any record already exists for that student/date; in these cases, the entire batch rolls back and no partial batch is saved.
- `POST /api/v1/attendance/sections/{section_id}/bulk` — class-aware bulk attendance for active students currently enrolled in that section. If a student is not an active member of the section, or any duplicate attendance record exists, the whole batch rolls back.
- `GET /api/v1/attendance` — list records, optionally filtered by `attendance_date`, `branch_id`, or `student_id`.
- `GET /api/v1/attendance/reports/students?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&branch_id=...&limit=100&offset=0` — paginated per-student attendance counts for active students in the organization. Students with no records remain in the report with zero counts and a `null` rate; no record is not treated as absence.
- `GET /api/v1/attendance/summary?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&branch_id=...` — summarize recorded statuses over an inclusive date range. The rate is `(present + late) / (total recorded - excused) × 100`; it is `null` when there are no non-excused records. Missing attendance entries are not inferred.
- `PATCH /api/v1/attendance/{attendance_id}` — correct a record; a reason is required and the previous/new status is stored in a change-history table.
- `GET /api/v1/attendance/{attendance_id}/history` — inspect recorded corrections.

The prototype enforces one attendance record per student per date within an organization and prevents linking records to a student from another organization. Requests still use `X-Organization-ID` as a development scoping header only; it is **not authentication or authorization**. This storage is not the approved production schema and must not be used with real student data.

### Backend tests

Run from the `backend` directory:

```bash
python -m pip install -r requirements.txt
python -m pytest -q
```

### Attendance register UI (development prototype)

The Attendance navigation screen now connects to the prototype API. It loads the student list and date-filtered attendance records, records one student's status for a selected date, and allows a correction only with a required reason. Duplicate student/date records are reported from the API. Status options are present, absent, late, and excused; the interface has English and Amharic labels. The screen is not an offline-first workflow and still uses the disposable SQLite store and caller-provided organization header. Do not use real student data.

The backend test suite has since grown; use the latest validation result and `python -m pytest -q`. Frontend production build could not be verified in this environment because npm dependency installation timed out; run `npm install` and `npm run build` locally before relying on the UI.

### Attendance summary report (development prototype)

The Attendance screen now includes a date-range summary with total recorded, present, absent, late, excused, and attendance-rate figures. The API validates the date range and supports an optional branch filter. The percentage definition is displayed in the interface to avoid implying that unrecorded attendance counts as absence. These are aggregate counts from the disposable SQLite prototype only.


### Bulk class attendance API (development prototype)

`POST /api/v1/attendance/bulk` accepts an `attendance_date` and a `records` array of `{ "student_id": "...", "status": "present|absent|late|excused", "note": "optional" }`. It supports up to 500 entries per request. The operation is transactional: a duplicate student/date or unknown student rejects the full batch rather than leaving a partial register. Duplicate student IDs within the request are rejected during request validation. This endpoint is API-ready for future class-level UI integration; the current screen still records one student at a time.

Validation run for this increment: `python -m pytest -q` — **25 passed**. Frontend build remains unverified because npm dependencies could not be installed in the earlier environment. Production authentication, server-enforced tenant access, PostgreSQL persistence, and offline synchronization are not implemented.

### Bulk attendance register UI (development prototype)

The Attendance screen now includes a bulk entry panel. For the selected date, it lists students who do not yet have a record, allows a status to be selected per student, and submits the pending students to `POST /api/v1/attendance/bulk` in one request. Students already recorded for that date are excluded from the draft list. The server remains the final authority: if any entry conflicts or fails validation, the entire batch is rejected without partial writes. The bulk-attendance UI supports an optional section selector. Choosing a section restricts the visible roster and uses the section-aware endpoint; leaving it unselected uses the organization-wide prototype roster.

The backend suite passes **25 tests** (`python -m pytest -q`). Frontend compilation has not been verified because dependencies are not installed in this environment. Install frontend dependencies and run `npm run build` before relying on the UI. Production authentication, server-enforced tenant access, PostgreSQL persistence, and offline synchronization remain unimplemented.

## Academic assessments and results (development prototype)

The Academics screen is now connected to the development API. It supports creating a draft assessment (subject, title, term, branch, optional section, date, maximum score), listing assessments, recording/updating per-student scores, and publishing an assessment. When a section is selected, the student roster is limited to active enrollments in that section, and the API rejects results for students not actively enrolled there. Scores use Python `Decimal`/SQLite decimal strings in the API path rather than binary floating-point arithmetic. A score cannot exceed the assessment maximum. Publishing requires at least one saved result and locks further score edits (HTTP 409). Results and assessments are scoped by the `X-Organization-ID` development header.

Endpoints:

- `POST /api/v1/academics/assessments`
- `GET /api/v1/academics/assessments?branch_id=main`
- `GET /api/v1/academics/students?branch_id=main`
- `POST /api/v1/academics/assessments/{assessment_id}/results`
- `GET /api/v1/academics/assessments/{assessment_id}/results`
- `GET /api/v1/academics/assessments/{assessment_id}/results/{student_id}/history` — draft-time result creation/update history, scoped to the organization.
- `POST /api/v1/academics/assessments/{assessment_id}/publish`
- `GET /api/v1/academics/reports/students/{student_id}?section_id=...&term=Term%201` — report-card view using published assessments for the student's active section enrollment. Draft assessments are excluded; missing scores remain `null` and are not silently counted as zero. Totals and percentages include only assessments with recorded scores.

This is not yet the approved production grading model: assessment weighting, configurable grading scales, moderation/approval workflow, immutable report snapshots/revisions, transcript generation, and proper permission enforcement are not implemented. Publishing is a prototype lock only. Do not use real student data. Production migrations remain blocked pending explicit approval of the consolidated schema.


## Academic year, class, section and enrollment API (development prototype)

The backend now provides foundational classroom structure endpoints. All require `X-Organization-ID`, which is only a development tenant selector and is not authentication.

- `POST /api/v1/classrooms/academic-years` and `GET /api/v1/classrooms/academic-years` — create/list named school years with start/end dates; reversed date ranges are rejected.
- `POST /api/v1/classrooms/class-levels` and `GET /api/v1/classrooms/class-levels` — create/list organization-scoped levels such as Grade 1.
- `POST /api/v1/classrooms/sections` and `GET /api/v1/classrooms/sections?branch_id=main&year_id=...` — create/list branch, year and level scoped sections with optional capacity.
- `POST /api/v1/classrooms/enrollments` and `GET /api/v1/classrooms/enrollments?section_id=...&status=active` — enroll a student into a section and list enrollments.
- `GET /api/v1/classrooms/sections/{section_id}/students` — list active students currently enrolled in the section; returns 404 for a section outside the selected organization.

The prototype checks that the student and section belong to the same branch, enforces optional section capacity, prevents a student from having more than one active enrollment within an organization, and blocks cross-organization references. These are development SQLite constraints and service checks, not a production security guarantee. Enrollment lifecycle actions (transfer, withdrawal, completion) and audited enrollment history are not yet implemented. Class-aware attendance is available through the section bulk endpoint and optional section selector in the attendance screen. Assessment creation supports an optional section ID; section-bound assessments list and accept results only for currently enrolled students, while older branch-wide assessments remain supported for compatibility.

Example sequence: create an academic year, create a class level, create a section using both returned IDs, then enroll a student using the section ID. The interactive OpenAPI page at `/api/v1/docs` exposes request shapes.

**Earlier validation for this increment:** `python -m pytest -q` — 35 passed. See the latest development increment below for current validation. The React frontend build remains unverified because npm dependency installation timed out earlier. Production migrations remain on hold pending explicit final-schema approval.

### Classes and enrollment UI (development prototype)

The **Classes & enrollment** navigation page connects to the development API and allows users to:

- Create academic years with start/end date validation.
- Create grade levels with a display sort order.
- Create sections scoped to a branch, academic year, and grade level, with an optional capacity.
- Enroll active students into sections and view the resulting enrollment roster.

The backend rejects duplicate active enrollments, cross-branch student/section pairs, inactive students or archived sections, and section capacity overflow. This workflow is still backed by disposable SQLite storage; it does not yet provide enrollment completion/withdrawal UI, a formal branch directory, class-aware attendance, or a production-grade permission model. The frontend build remains unverified in environments where npm dependencies cannot be installed.


## Latest development increment: section roster and section-aware attendance API

The prototype now exposes `GET /api/v1/classrooms/sections/{section_id}/students` to retrieve only active students with an active enrollment in that organization-scoped section. It also exposes `POST /api/v1/attendance/sections/{section_id}/bulk` for atomic attendance entry restricted to those enrolled students. Archived/missing sections and non-enrolled students are rejected, and any invalid item rolls back the entire batch. The Attendance screen now has an optional section selector for bulk attendance. Selecting a section loads its enrolled roster and sends the batch to the section-aware endpoint; leaving the selector on “All students” keeps the general prototype workflow.

Latest validation: `python -m pytest -q` — **56 passed**; `python -m compileall -q app` succeeds. The frontend build remains unverified because npm dependencies were not successfully installed. The API remains a disposable SQLite prototype, and production migrations remain on hold pending explicit final-schema approval.


### Section-aware assessments (development increment)

`POST /api/v1/academics/assessments` accepts an optional `section_id`. If supplied, the section must exist within the organization, be active, and match the assessment branch. `GET /api/v1/academics/students?branch_id=branch-1&section_id=...` returns active students with active enrollment in that section. `POST /api/v1/academics/assessments/{assessment_id}/results` rejects a student who is not currently enrolled in the selected section. The Academics screen now has a section selector; leaving it blank preserves branch-wide prototype behavior. A small SQLite compatibility alteration adds the optional column to an existing disposable development database; this is not a production migration.

**Latest backend validation:** `python -m pytest -q` — 41 passed; `python -m compileall -q app` succeeded. Frontend build remains unverified because npm dependencies are absent.


### Published assessment report-card API and UI (development prototype)

The Reports screen now offers a section, active student, and term selector and displays published assessment scores with a simple total and percentage. The API route `GET /api/v1/academics/reports/students/{student_id}?section_id=...&term=...` requires an active enrollment in the selected section and scopes records by the organization development header. Draft assessments are omitted. Missing scores remain visibly missing; aggregate totals only use assessments that have a score, so a partial total is not presented as a complete final grade. This output is a live projection, not an immutable approved report card; no grading scale, weighting, approved published-result amendment workflow, authorization roles, or server-generated PDF is implemented. Draft-time score creates/updates are recorded in a prototype history table and can be read through the result-history endpoint; the history does not identify an authenticated actor because authentication is not implemented.

Latest backend validation for this increment: `python -m pytest -q` — 44 passed; `python -m compileall -q app` succeeded. Frontend build remains unverified because dependencies have not been installed successfully in this environment. Production migrations remain on hold pending explicit final-schema approval.

### Finance prototype endpoints

- `POST /api/v1/finance/bills` — create a student fee bill using integer minor units.
- `GET /api/v1/finance/bills?student_id=...` — list bills and reconciled outstanding balances.
- `POST /api/v1/finance/payments` — record a provisional payment with explicit manual bill allocations.
- `GET /api/v1/finance/payments?student_id=...` — list provisional/reconciled payments.
- `POST /api/v1/finance/payments/{payment_id}/reconcile` — prototype reconciliation that atomically posts append-only student-account entries and a matching general-ledger journal.
- `GET /api/v1/finance/students/{student_id}/account` — student account journal balance summary by currency.

The Finance screen in the React frontend is connected to these endpoints and supports selecting a student, creating a fee bill, recording a provisional payment with one manual bill allocation, viewing balances/history, and invoking prototype reconciliation. Amount inputs are displayed in birr and sent as integer minor units.

### General ledger prototype endpoints

- `POST /api/v1/finance/ledger/accounts` and `GET /api/v1/finance/ledger/accounts` — create/list organization-scoped chart-of-account entries.
- `POST /api/v1/finance/ledger/journals` — post a balanced, multi-line journal in one currency; every line must debit or credit exactly one side, accounts must be active and match the journal currency, and the journal must balance.
- `POST /api/v1/finance/ledger/journals/{journal_id}/reverse` — create an append-only reversing journal with a required reason. The original remains unchanged; a journal can be reversed only once, and reversal journals cannot themselves be reversed.
- `GET /api/v1/finance/ledger/journals?currency=ETB&limit=50&offset=0` — browse posted journals with their lines and pagination; optionally filter by `account_id`.
- `GET /api/v1/finance/ledger/accounts/{account_id}/activity?limit=50&offset=0` — view an account ledger with running net-debit balance and page through entries.
- `GET /api/v1/finance/ledger/trial-balance?currency=ETB` — summarize posted debit/credit totals by account and indicate whether the trial balance balances.

Posted journal headers and lines are append-only in this disposable SQLite prototype. Corrections should eventually be made by explicit reversal entries, not edits. Fee-bill creation now automatically posts Debit Student Accounts Receivable / Credit Tuition and Fee Revenue. Successful payment reconciliation posts Debit Cash and Payment Clearing, Credit Accounts Receivable for allocated amounts, and Credit Student Credit Liability for overpayments. These finance journal postings are committed in the same SQLite transaction as the bill/payment state change, and repeated reconciliation does not duplicate the journal. The prototype creates reserved accounts `1000`, `1100`, `2100`, and `4000` for each organization/currency when needed; conflicting reserved account codes/types are rejected.

Finance prototype caveats: amounts are integer minor units (ETB uses 100 minor units per birr); bill identifiers are internal IDs, not official bill numbers; payment references are provisional (`TMP-...`), not official receipts; no production cashier permissions, dual-control approval, refund flow, or central sequence allocator exists. Reconciliation endpoint is intentionally unauthenticated for local development only and must not be exposed to real users. Do not use real financial or personal data. Production migrations remain on hold pending explicit schema approval.


### Finance screen: general-ledger UI increment

The Finance page now also includes a basic General Ledger interface in Amharic and English. Users can create organization-scoped accounts (asset, liability, equity, revenue, expense), post a simple two-account debit/credit journal, browse ETB journal history in 50-entry pages with a total count, and view the ETB trial balance. Each eligible journal has a reversal-reason field and a confirmation step; the UI calls the append-only reversal endpoint and refreshes the ledger. Reversed originals are marked and cannot be reversed again from the UI. The API validates that the journal is balanced and that both accounts are active and use the selected currency. This screen is a prototype convenience UI and does not provide authenticated accountant permissions, dual-control approval, or period close. Fee bills and reconciled payments now generate corresponding balanced ledger journals automatically; the UI can also still post simple manual two-account journals. Frontend build validation is still pending because dependencies could not be installed in this environment.


### General ledger browsing increment

The prototype now exposes paginated journal browsing (`GET /api/v1/finance/ledger/journals`) and tenant-scoped account activity (`GET /api/v1/finance/ledger/accounts/{account_id}/activity`). Journal results include line-level account codes/names and debit/credit totals; account activity includes a running net-debit balance that remains consistent when requesting later pages. Unknown or cross-organization account IDs return 404. Pagination is bounded to 1–200 rows per request. These are development endpoints only; the caller-controlled organization header is not authorization.

Latest backend validation for this increment: `PYTHONPATH=. python -m pytest -q` — **59 passed**; `PYTHONPATH=. python -m compileall -q app` succeeded. Frontend build remains unverified because dependencies were unavailable in the earlier environment.


### Ledger retry safety (development prototype)

`POST /api/v1/finance/ledger/journals` accepts an optional `Idempotency-Key` header (1–128 non-whitespace characters). The key is scoped to the organization. Repeating a request with the same key and same normalized payload returns the existing journal instead of posting a duplicate; reusing the key with a different payload returns HTTP 409. This is useful for retry behavior during flaky connectivity, but it does not implement the full offline outbox/sync protocol and is not a substitute for authenticated tenant authorization. The local prototype store may add these columns in place; production schema migrations remain on hold pending approval.

### Ledger reversals (prototype)

Posted ledger journals are immutable. To correct a posted journal, call `POST /api/v1/finance/ledger/journals/{journal_id}/reverse` with JSON such as `{"reason":"Wrong student account"}`. The API posts an exact opposite-line journal, stores the original journal reference, requires a reason, and rejects cross-organization IDs, repeat reversals, and attempts to reverse a reversal. The original and reversal both remain visible in the ledger and offset in the trial balance. The route is development-only; opt-in role checks are coarse and do not replace authenticated approval workflows or dual control.


## Finance audit events (development prototype)

`GET /api/v1/finance/audit-events` returns organization-scoped, paginated events. Optional filters: `entity_type`, `entity_id`, and `event_type`; `limit` is 1–200 and `offset` is zero or greater. The prototype records finance bill creation, payment recording/reconciliation, ledger-account creation, journal posting, and journal reversal. Example:

```bash
curl 'http://127.0.0.1:8000/api/v1/finance/audit-events?limit=50' \
  -H 'X-Organization-ID: demo-school'
```

Audit rows are append-only in the local SQLite prototype (update/delete triggers) and avoid copying student names or other unnecessary personal details. Finance bill/payment/reconciliation and ledger-account/journal/reversal events are inserted using the same SQLite transaction as their corresponding business write; a failed audit insert therefore rolls the business write back too. The prototype deliberately does not invent an actor identity: `actor_id` remains empty until real authentication exists. This is not a tamper-proof production audit system: local database administrators can bypass application-level controls, and the caller-controlled organization header is not a security boundary. Do not use real data.


### Detailed student fee statement (prototype)

`GET /api/v1/finance/students/{student_id}/statement?limit=50&offset=0` returns the append-only student fee journal, including bill/payment references and a running balance per currency. The running balance is computed across the complete journal before pagination, so each returned row retains its correct balance. Results are organization-scoped and pagination is bounded to 200 rows per request. This endpoint is development-only and does not replace a reviewed production statement/reporting design.

### Shared guardian directory search (prototype)

`GET /api/v1/guardians?q=Almaz&limit=50&offset=0` searches guardian identities within the selected organization by given name, family name, phone, or email. It returns a bounded, paginated directory with a `linked_student_count`, but deliberately does not return student IDs or student names. The result can be used to choose an existing guardian identity and link it to another student with `POST /api/v1/students/{student_id}/guardians/{guardian_id}/link`, avoiding duplicate guardian records for siblings. Search terms treat `%` and `_` as literal characters rather than SQL wildcard patterns. This is still a development endpoint: organization selection uses the caller-controlled `X-Organization-ID` header, and production access control is not implemented.

Latest backend validation after this increment: `python -m pytest -q` — **72 passed**; `python -m compileall -q app` succeeded. Frontend build remains unverified because frontend dependencies are not installed in this environment.

### Request correlation IDs

Every API response includes `X-Request-ID`. A caller-provided ID is preserved only when it is 1–128 characters from the safe set `A-Z`, `a-z`, `0-9`, `.`, `_`, `:`, and `-`; otherwise the API generates a UUID. Use this value to correlate a client report with server-side logs. This header is a diagnostic identifier, not an authentication credential.

- Student listing supports organization-scoped case-insensitive substring search via `GET /api/v1/students?q=...`, branch filtering, and pagination.
- The Students frontend now sends its search query to the API and uses server-reported totals with 50-record Previous/Next pagination, rather than searching only the first 200 records in the browser.

- Student deactivation is a reason-required soft status change; the status update and append-only audit event are committed atomically. Repeated deactivation returns `409`, and organization scoping is enforced.


## Latest development increment: exact finance amount conversion

The Finance UI now converts amount text into integer minor units with decimal-string arithmetic instead of `Number(value) * 100` and `Math.round`, avoiding binary floating-point edge cases for ETB values. It rejects negative, malformed, over-precision, and out-of-range amounts before submitting them, and prevents a payment allocation from exceeding the payment amount. The helper is isolated in `frontend/src/money.mjs` with repeatable dependency-free Node tests in `frontend/tests/money.test.mjs`.

Run the frontend helper tests with `npm test` from `frontend/`. These tests do not replace the full React/TypeScript production build; the latter remains unverified in this environment because frontend dependencies have not installed successfully. Production schema migrations remain on hold pending explicit final-schema approval.

## Latest development increment: finance student directory pagination

The bilingual Finance page now searches students through the server using `GET /api/v1/students?q=...` and displays 50 results per page with Previous/Next controls and the server-reported total. This avoids limiting the finance student picker to the first 200 records and keeps `%`/`_` search handling on the existing API implementation. Frontend syntax transpilation and the Node money tests pass; a full `npm run build` remains blocked in this environment because React, React DOM, and Lucide dependencies are not installed.

### Authentication middleware regression checks (2026-10-19)

Added regression coverage for two important staged-auth behaviors: the verified access-token organization is used when `X-Organization-ID` is omitted, and a conflicting organization header is rejected with HTTP 403. Also verified that the teacher role cannot mutate finance bills. Current backend test run: `109 passed, 25 subtests passed`. These are prototype-level checks only; they do not replace production authorization review, PostgreSQL tenant isolation, or branch/record-level access control.

## Offline synchronization design

The protocol draft is available in [`docs/OFFLINE_SYNC_PROTOCOL.md`](docs/OFFLINE_SYNC_PROTOCOL.md). The prototype now has IndexedDB outbox primitives, a bounded batch API for student-profile create/update, draft assessment result create/update, and attendance create/update, and a client transport helper that validates the complete server response before acknowledging queued mutations. The dashboard now includes a manual sync panel that counts queued items and can push a validated batch for the current organization/device/actor. The server supports student-profile create/update, draft assessment result create/update, and attendance create/update mutations; however, the single-record and bulk attendance forms are the only forms currently wired to enqueue offline mutations. Assessment-result sync is supported by the prototype API, but assessment forms are not yet wired to the outbox; background retry, complete domain wiring, and production authentication remain incomplete. Production migrations remain on hold pending explicit schema approval.

## CI and honest sync status

A GitHub Actions workflow (`.github/workflows/ci.yml`) runs backend tests/compile checks and frontend tests/build checks on pushes and pull requests. The dashboard has a manual offline-sync panel backed by the IndexedDB queue and the batch transport helper. The single and bulk attendance forms can queue records locally while offline; student profile and assessment forms are not yet connected to the outbox. Dashboard metrics and activity feed remain demo data.

The frontend dependency installation timed out in the authoring environment, so `npm run build` has **not** been locally verified. CI is configured to perform that build on a networked runner; treat any CI failure as unresolved until fixed.

### Development database backup helper

A SQLite backup/verification helper is included under `backend/scripts/sqlite_backup.py`. It uses SQLite's online backup API and checks database integrity and foreign keys. See `backend/README.md` for commands. It is intended only for the disposable development database and is not a production backup or disaster-recovery solution.


### Backup helper hardening (latest increment)

The development SQLite backup utility now rejects symbolic-link destinations, refuses to clobber an existing destination unless `--overwrite` is explicit, and publishes new backups with a no-clobber filesystem operation to avoid a check-then-overwrite race. Additional tests cover snapshot isolation and corrupted database detection. These changes improve the local development utility only; they do not provide production disaster recovery or a restore guarantee.

Backup helper regression coverage now also verifies explicit overwrite behavior and rejection of databases with foreign-key violations. Latest local validation: backend `118 passed, 25 subtests passed`; `python -m compileall -q app scripts` succeeded; frontend dependency-free tests `3/3` passed. A fresh attempt to install frontend dependencies timed out, so the full TypeScript/Vite production build remains unverified.

### Offline queue development status

The frontend includes tested IndexedDB outbox primitives in `frontend/src/offlineOutbox.mjs` that durably queue versioned mutation envelopes in supported browsers. Current forms are not wired to the outbox and local browser storage is not encrypted. Do not use it for real student or financial data yet. See `docs/OFFLINE_SYNC_PROTOCOL.md`.

### Offline sync client protocol helpers (prototype only)

The browser outbox module includes tested `buildSyncBatch` and `validateSyncResponse` helpers, and `frontend/src/offlineSync.mjs` provides a transport orchestration helper. The client enforces a 100-mutation / 256 KiB batch ceiling, rejects mixed tenant/device/actor batches and duplicate IDs, and validates one durable server outcome per mutation before acknowledging it. The dashboard now exposes manual queue refresh and sync actions with visible acknowledgement/conflict/rejection counts. This is not yet end-to-end offline operation: only single-record attendance creation is wired to the queue; background retry and conflict-resolution UI are missing, and real student/financial data must not be cached in the browser prototype.


### Current offline-sync API status (prototype)

`POST /api/v1/sync/batch` supports student-profile create/update, attendance-record create/update, and draft-assessment-result create/update mutations in the disposable SQLite development store. Student profile, attendance, and draft assessment result creates initialize entity version 1; updates require `base_version`, use optimistic concurrency, increment the version when data changes, and append an audit/history entry in the same transaction as the domain write and idempotency outcome. Exact retries return `duplicate`; stale versions return `conflict`; deletes and unsupported entities are rejected. Other entities, production authentication/persistence, retention, full end-to-end client sync, and multi-device concurrency validation remain incomplete. This prototype is not production-ready. See `docs/OFFLINE_SYNC_PROTOCOL.md`.


### Manual sync panel and retry safety (2026-10-19)

The dashboard sync panel now reads the IndexedDB outbox count, provides a manual queue refresh and push action, displays acknowledgements/conflicts/blocked outcomes, and tracks browser online/offline changes. A protocol `retry` outcome is now deliberately left pending rather than being passed to the acknowledgement function. Type declarations were added for the JavaScript outbox/transport modules. The form-to-outbox wiring, automatic retry/backoff, conflict-resolution UI, and full-domain sync remain unfinished. Validation: backend `128 passed, 25 subtests passed`; frontend dependency-free tests `13/13 passed`; `python -m compileall -q app scripts` passed. The TypeScript/Vite build remains unverified because React/Vite dependencies are not installed in this environment.

### Latest offline outbox review improvement (2026-10-19)

The dashboard sync panel reads local outbox status categories and shows counts for pending, acknowledged, conflicting, and blocked mutations. Up to eight recent conflict/blocked items are listed for manual review with entity type, operation, and a shortened mutation ID; these items remain stored locally and require manual resolution. When the browser emits an `online` event, the panel automatically attempts to push pending mutations for the current organization/device/actor; a lock prevents overlapping sync attempts. This reconnect retry does not implement exponential backoff, background service-worker sync, conflict resolution, edit/rebase, or full-domain sync, and domain forms are not all wired to enqueue mutations. Validation for this increment: backend `128 passed, 25 subtests passed`; frontend `14/14 passed`; Python compile checks passed. The full TypeScript/Vite production build remains unverified because frontend dependencies are not installed in this environment.


### Offline attendance form enqueue (2026-10-19)

The single-record and bulk attendance forms detect offline mode before sending and persist versioned `attendance_record` create envelopes to IndexedDB. Bulk attendance is queued as individual idempotent create commands because the sync protocol accepts attendance mutations, not bulk commands. If the network request fails with a fetch `TypeError`, the UI attempts to queue the same commands locally; HTTP validation/business errors are still shown and are not silently queued. Queued records are reflected optimistically in the current attendance view to reduce accidental duplicate entry. The UI instructs the user to open the Sync panel when connectivity returns. This does not make the whole app offline-ready: student lists still need to have loaded beforehand, other domain forms are not queued, and background sync/conflict resolution remain incomplete. Validation: backend `128 passed, 25 subtests passed`; frontend `14/14 passed`; Python compile checks passed. The full TypeScript/Vite build could not be completed because frontend dependencies (including React and Vite) are not installed in this environment.
### Offline sync review diagnostics

The browser outbox now retains bounded server diagnostics for conflict/rejection review (reason and current/entity version where supplied), and the Sync panel displays those details. This improves diagnosis only; it does not automatically resolve conflicts or authorize resubmission.


### Conflict retry safety

A conflicted offline mutation remains preserved for audit/review. The client helper `createConflictRetryEnvelope` prepares a separate pending envelope only when the server supplied a valid `current_version`; the reviewer must provide an explicitly revised payload and a fresh UUID. The new envelope uses that current version as `base_version`. It does not alter or delete the original conflict. This is a preparation primitive, not an automatic merge or a user-interface retry workflow.


### Manual conflict retry UI

The Sync panel now provides an explicit review editor for conflicted `update` mutations only when the server returned a valid `current_version`. It pre-fills the stored JSON payload for review/editing and, after user confirmation, enqueues a separate mutation with a fresh UUID and that current version as `base_version`. The original conflict remains in the outbox. Invalid JSON, unavailable UUID generation, and IndexedDB failures are surfaced in the UI. This is not an automatic merge; create conflicts and blocked items still require domain-specific handling. The frontend unit tests pass (18/18); the TypeScript/Vite build is only verified if dependencies are installed.

## Windows desktop installer (prototype)

An Electron wrapper and Windows x64 NSIS installer build target are available. See [`docs/windows/INSTALLER.md`](docs/windows/INSTALLER.md) for build instructions and limitations. On Windows with Node.js 22 and network access, run `cd frontend`, `npm install`, `npm test`, then `npm run dist:win`. The installer packages the frontend only; the FastAPI backend and its database must run separately. A GitHub Actions workflow can build and upload the installer artifact. The installer has not been built or smoke-tested in this environment, so treat it as a build path rather than a released executable.
#   m o j a w  
 