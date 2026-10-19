# Offline synchronization protocol — design draft

**Status: design draft plus development-only prototype. Not approved for production migrations.**

This document defines a safe target for Windows clients that may work without internet access and later synchronize with the central service. A narrow disposable-SQLite/browser prototype exists as described below; it is not production sync and does not authorize production schema migrations.

## 1. Core invariants

1. A locally accepted write and its outbox envelope are committed in one SQLite transaction. A client must never show a saved local change if its durable outbox entry was not committed too.
2. Every mutation has a stable UUID `mutation_id`, generated once when the user confirms the action. Retries reuse that ID and the exact canonical payload.
3. The server records the idempotency outcome in the same transaction as the business mutation. Replaying the same ID and payload returns the original outcome; replaying the same ID with a different payload is a conflict.
4. Delivery is **at least once**. The system must not depend on exactly-once networking.
5. The central PostgreSQL database is authoritative for centrally allocated identifiers, permissions, published results, financial reconciliation, and final conflict decisions.
6. A client must not delete an outbox item merely because it sent a request. It may mark it acknowledged only after validating the server's durable acknowledgement.
7. A server response can be applied locally only after validating organization, entity type, mutation ID, and schema version.

## 2. Proposed envelope

```json
{
  "protocol_version": 1,
  "mutation_id": "stable UUID",
  "organization_id": "organization identifier",
  "device_id": "registered device identifier",
  "actor_id": "authenticated actor identifier",
  "entity_type": "attendance_record",
  "entity_id": "client-generated UUID where allowed",
  "operation": "create",
  "base_version": null,
  "schema_version": 1,
  "created_at_device": "RFC 3339 timestamp; informational only",
  "payload": {},
  "payload_sha256": "hash of canonical payload"
}
```

The example is illustrative, not a committed API schema. Device time is not trusted for authorization, financial ordering, or audit ordering. The server supplies authoritative timestamps and versions. Canonicalization rules must be versioned and tested before payload hashes are relied on.

## 3. Client outbox state machine

`pending -> in_flight -> acknowledged`

- `pending`: durable local change exists and has not been sent successfully.
- `in_flight`: a worker has claimed the row with a short lease; process termination must allow the lease to expire.
- `acknowledged`: server has durably accepted or explicitly rejected the mutation and returned a stable outcome.
- `conflict`: server needs a human or domain-specific resolution. Keep the original envelope and show a clear status; do not silently discard it.
- `blocked`: the mutation cannot be sent because authorization expired, schema is unsupported, or a prerequisite is missing.

An acknowledged envelope may be compacted only after the server response and resulting authoritative state have been committed locally. Keep a bounded diagnostic record with mutation ID and outcome for support.

## 4. Batch API behavior

A future batch endpoint should accept a bounded number and byte size of envelopes, validate every envelope, and return one outcome per `mutation_id`. Partial success must be explicit; a batch-level HTTP success must not mean every mutation succeeded. Responses should distinguish:

- `accepted`: mutation committed and outcome durable;
- `duplicate`: same mutation ID and payload was already committed; return original result;
- `conflict`: valid request but incompatible with current authoritative state;
- `rejected`: invalid, unauthorized, unsupported, or policy-prohibited request;
- `retry`: transient failure; client keeps the item pending.

Enforce request limits, schema versions, authenticated organization/device/actor binding, and rate limits. Never trust organization or actor IDs merely because they appear in the envelope.

## 5. Conflict policy by domain

| Domain | Proposed policy |
|---|---|
| Attendance | Unique key is organization + student + date. Duplicate creates become a conflict; corrections require a reason and an authorized actor. Never use last-write-wins for corrections. |
| Student profile | Field-level merge only for explicitly mergeable low-risk fields. Identity, enrollment, branch transfer, and status changes require conflict review. |
| Enrollment / class roster | Server validates active enrollment, branch, capacity, academic year, and permissions at synchronization time. A locally accepted change can be rejected centrally with a visible reason. |
| Assessment marks | Draft entries may sync with base version checks. Published results are immutable; changes after publication require a revision workflow and audit trail. |
| Bills / payments / receipts | Never invent official numbers offline. Store local provisional references only. Central reconciliation assigns official receipt numbers and is idempotent. Financial conflicts are never auto-merged. |
| Ledger | Only balanced, authorized, idempotent journal commands may post. Posted journals are reversed by a new linked journal, never edited or deleted. |

## 6. Authorization and offline lease

Offline access must be bounded by a signed, device-bound authorization lease with an explicit expiry and permitted capabilities. A local clock rollback must not extend access. Sensitive actions such as refunds, official receipt issuance, financial reconciliation, role changes, and result publication require online authorization or a separately approved control. Revocation cannot reach a disconnected device immediately; the product must disclose this risk and restrict cached data accordingly.

A 24-hour lease is a proposed product requirement, not implemented behavior. Its signing, device binding, secure storage, clock rollback defense, revocation behavior, and recovery flow require a threat model and review before implementation.

## 7. SQLite requirements

- Enable `PRAGMA foreign_keys = ON` for every connection.
- Use WAL where appropriate and configure busy timeout deliberately.
- Commit each local business mutation and outbox insert atomically.
- Use explicit schema migrations and preserve a recoverable local backup before upgrade.
- Store money as integer minor units and scores as exact decimal values.
- Do not store bearer tokens, bootstrap secrets, or long-lived signing keys in ordinary SQLite tables.
- Treat a device as potentially lost or compromised; minimize sensitive cached data and encrypt the device volume/storage according to deployment policy.

## 8. Required acceptance tests before calling sync implemented

1. Process crash between local mutation and outbox insert cannot leave only one side committed.
2. Process crash after server commit but before client acknowledgement does not duplicate the business mutation on retry.
3. Same mutation ID + same payload returns the original result; same ID + different payload is rejected as a conflict.
4. Multiple devices syncing the same attendance key produce a deterministic, visible conflict.
5. Out-of-order updates are checked against base versions and domain policy.
6. Expired or revoked authorization cannot perform prohibited server-side actions.
7. Unsupported protocol/schema versions remain queued and are visible to the operator.
8. Network loss, timeout, duplicate delivery, server restart, local restart, and partial batch failure are tested.
9. Local outbox corruption or disk-full errors never display a write as safely queued.
10. Restore drills demonstrate that the central database and audit trail can be recovered consistently.

## 9. Implementation sequence

1. Approve entity IDs, schema versioning, authorization model, retention, and conflict policy.
2. Finalize PostgreSQL schema and migration/recovery process; do not generate production migrations before explicit schema approval.
3. Implement authenticated device registration and server-side idempotency storage transactionally.
4. Implement the local SQLite schema, migrations, atomic outbox service, and unit tests.
5. Implement bounded batch upload, per-item outcomes, retries with jitter, and conflict UI.
6. Integrate one low-risk domain first (attendance), run two-device and fault-injection tests, then expand domain by domain.
7. Complete threat modeling, security review, restore drills, and pilot before production rollout.

## 10. Browser outbox prototype (local storage only)

The frontend contains `src/offlineOutbox.mjs`, which builds versioned mutation envelopes and stores them in IndexedDB through `enqueueMutation`, `listPendingMutations`, and `acknowledgeMutation` helpers. The helper refuses unsupported entity types and unsafe JSON payload values, keeps a stable mutation UUID, and does not treat unavailable IndexedDB as a successful save. It distinguishes `accepted`/`duplicate`, `conflict`, and `rejected` outcomes in local status.

**Important boundary:** attendance create forms and draft assessment score submissions are wired to enqueue offline mutations. Score submission is queued when the browser reports itself offline and requires the assessment and student roster to have been loaded already. When the API is reachable again, pending queued scores are overlaid on fetched results so they remain visible after a reload; conflicted items are not silently overlaid. The development-only `POST /api/v1/sync/batch` endpoint supports student-profile create/update, draft assessment result create/update, and attendance create/update; it is not production-authenticated. The academic UI now caches previously fetched branch assessment lists, active sections, student rosters, and assessment results in a separate organization/actor-scoped IndexedDB snapshot store. When the API is unavailable, it may show those cached records with a stale-data notice; a roster/results cache must have been populated while online first. The cache is not encrypted and has no expiry or remote wipe; do not cache real student or financial data on shared devices. The UI is not fully offline-capable. Acknowledgement is performed only after validating the server response, but production authorization and persistence are not implemented.

## 11. Client batch construction and response validation

`src/offlineOutbox.mjs` now exports `buildSyncBatch` and `validateSyncResponse` as pure, tested protocol helpers. Batch construction accepts 1–100 pending mutations, refuses mixed organization/device/actor identities and duplicate mutation IDs, strips local-only status fields, and enforces a 256 KiB encoded request limit. Response validation requires matching protocol, organization and device, exactly one known outcome for every submitted mutation, no unknown/duplicate IDs, and an explicit `durable: true` assertion before `accepted` or `duplicate` can be trusted. These checks are client-side defense in depth only: the server must independently authenticate identity and validate every envelope. The authenticated server batch endpoint is still not implemented, so these helpers do not synchronize data yet.

## 12. Prototype server endpoint: student, attendance, and draft assessment result mutations

`POST /api/v1/sync/batch` validates bounded protocol envelopes and persists idempotent outcomes in the disposable SQLite development store. It supports `student_profile` + `create/update`, `attendance_record` + `create/update`, and `draft_assessment_result` + `create/update`. Draft result mutations carry `assessment_id`, `student_id`, `score`, and optional `comment` in the payload; the envelope `entity_id` is the result ID. Result rows have a prototype version counter. Creates require a null base version and a unique assessment/student pair; updates require the current base version and matching result ID. The server rejects results above `max_score`, students outside the organization, students without active enrollment when an assessment is section-scoped, and any mutation against a published assessment. Result row changes, history rows, and idempotency outcomes are committed atomically. Deletes remain unsupported. Student creation validates the existing `StudentCreate` contract, rejects a globally reused student ID, and inserts the student, audit event, and idempotency outcome in one SQLite transaction. Student updates validate the `StudentUpdate` contract, require `base_version`, use a database-backed optimistic version, and append an audit event with changed fields atomically. Student profile versioning is maintained in the disposable SQLite prototype schema; student delete remains unsupported.

Update requires `base_version` and a payload containing the new status, correction reason, and optional note. The server checks the current version within a write-locked transaction; a matching version updates the record, increments its version, appends a correction-history row, and stores the idempotency outcome atomically. A stale version returns `conflict` and reports the current version without overwriting the row. Exact retries return `duplicate`; reusing a mutation ID with different content returns `conflict`. The ordinary attendance correction endpoint also increments the version.

Guardian links and other unsupported entity operations return a durable `rejected` outcome. Draft assessment results support create/update only; deletes return a durable `rejected` outcome. Student-profile update/delete requests and attendance delete requests are explicitly rejected. Invalid payloads, reused student IDs, unknown students/records, and attendance uniqueness/entity-ID conflicts are not applied. With authentication enabled, organization and actor IDs are checked against the authenticated token; in default development mode, the organization header is only a prototype boundary, not real authentication. The inbox table is development-only, has no retention/cleanup policy, and is not a production audit store. Student profile delete, guardian and finance sync; offline creation of assessments; complete end-to-end client/server orchestration; multi-device concurrency validation; production database support; and production authorization remain incomplete. This is a narrow, tested prototype—not a complete offline synchronization feature. Do not use real student or financial data.
### Client-side review metadata

The frontend may retain a bounded `reason`, `current_version`, or `entity_version` from a validated server outcome for local review. These fields are diagnostic only and do not replace the server as source of truth or constitute conflict resolution.


### Conflict retry safety

A conflicted offline mutation remains preserved for audit/review. The client helper `createConflictRetryEnvelope` prepares a separate pending envelope only when the server supplied a valid `current_version`; the reviewer must provide an explicitly revised payload and a fresh UUID. The new envelope uses that current version as `base_version`. It does not alter or delete the original conflict. This is a preparation primitive, not an automatic merge or a user-interface retry workflow.


### Manual conflict retry UI

The Sync panel exposes a manual JSON review editor only for `update` conflicts with a valid server `current_version`. After the user reviews and confirms the payload, the client creates a new mutation UUID and uses the reported version as `base_version`, then enqueues it separately. The original conflict is preserved. This does not resolve create/uniqueness conflicts, blocked/rejected commands, or merge domain fields automatically. A retry is a new user-approved command and may conflict again if the server changes before it arrives.
