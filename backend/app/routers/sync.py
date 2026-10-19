"""Development-only offline sync prototype for student create/update and attendance create/update.
Deletes and other entity operations remain explicitly rejected.
"""
from __future__ import annotations
import hashlib
import json
import uuid
from typing import Any, Literal
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from app.schemas.attendance import AttendanceCreate, AttendanceUpdate
from app.schemas.students import StudentCreate, StudentUpdate
from app.schemas.academics import ResultCreate
from decimal import Decimal, InvalidOperation
from app.services.student_store import db_session

router = APIRouter(prefix="/api/v1/sync", tags=["offline sync"])
SUPPORTED_ENTITIES = {"attendance_record", "student_profile", "guardian_link", "draft_assessment_result"}
SUPPORTED_OPERATIONS = {"create", "update", "delete"}

class MutationEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_version: Literal[1]
    mutation_id: str
    organization_id: str = Field(min_length=1, max_length=128)
    device_id: str = Field(min_length=1, max_length=128)
    actor_id: str = Field(min_length=1, max_length=128)
    entity_type: str
    entity_id: str = Field(min_length=1, max_length=128)
    operation: str
    base_version: int | None = Field(default=None, ge=0)
    schema_version: Literal[1]
    created_at_device: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any]

    @field_validator("mutation_id")
    @classmethod
    def valid_uuid(cls, value: str) -> str:
        try:
            return str(uuid.UUID(value))
        except (ValueError, AttributeError) as exc:
            raise ValueError("mutation_id must be a UUID") from exc

    @field_validator("entity_type")
    @classmethod
    def valid_entity(cls, value: str) -> str:
        if value not in SUPPORTED_ENTITIES:
            raise ValueError("unsupported entity_type")
        return value

    @field_validator("operation")
    @classmethod
    def valid_operation(cls, value: str) -> str:
        if value not in SUPPORTED_OPERATIONS:
            raise ValueError("unsupported operation")
        return value

class SyncBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_version: Literal[1]
    organization_id: str = Field(min_length=1, max_length=128)
    device_id: str = Field(min_length=1, max_length=128)
    mutations: list[MutationEnvelope] = Field(min_length=1, max_length=100)


def _ensure_table(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS prototype_sync_outcomes (
        organization_id TEXT NOT NULL,
        mutation_id TEXT NOT NULL,
        device_id TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        outcome_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (organization_id, mutation_id)
    )""")

@router.post("/batch", summary="Apply supported offline student, draft assessment result, and attendance mutations (prototype only)")
def sync_batch(batch: SyncBatch, request: Request, x_organization_id: str | None = Header(default=None)):
    if not x_organization_id:
        raise HTTPException(status_code=400, detail="X-Organization-ID is required")
    if batch.organization_id != x_organization_id:
        raise HTTPException(status_code=403, detail="Batch organization does not match request organization")
    auth_user = getattr(request.state, "auth_user", None)
    if auth_user and batch.organization_id != auth_user.get("org"):
        raise HTTPException(status_code=403, detail="Batch organization does not match authenticated organization")
    if auth_user and any(item.actor_id != auth_user.get("sub") for item in batch.mutations):
        raise HTTPException(status_code=403, detail="Mutation actor does not match authenticated user")
    if any(item.organization_id != batch.organization_id or item.device_id != batch.device_id for item in batch.mutations):
        raise HTTPException(status_code=422, detail="Every mutation must match batch organization and device")
    ids = [item.mutation_id for item in batch.mutations]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="Batch contains duplicate mutation IDs")

    results = []
    with db_session() as conn:
        _ensure_table(conn)
        # Serialize writers before checking idempotency outcomes.
        conn.execute("BEGIN IMMEDIATE")
        for mutation in batch.mutations:
            payload = mutation.model_dump(mode="json")
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            row = conn.execute(
                "SELECT request_hash, outcome_json FROM prototype_sync_outcomes WHERE organization_id=? AND mutation_id=?",
                (batch.organization_id, mutation.mutation_id),
            ).fetchone()
            if row:
                if row["request_hash"] != digest:
                    results.append({"mutation_id": mutation.mutation_id, "outcome": "conflict", "durable": True, "reason": "mutation_id_reused_with_different_payload"})
                else:
                    previous = json.loads(row["outcome_json"])
                    results.append({**previous, "outcome": "duplicate", "durable": True})
                continue
            outcome = {"mutation_id": mutation.mutation_id, "outcome": "rejected", "durable": True}
            if mutation.entity_type == "student_profile":
                if mutation.operation == "delete":
                    outcome["reason"] = "student_profile_delete_is_not_supported"
                elif mutation.operation == "create" and mutation.base_version is not None:
                    outcome["reason"] = "base_version_must_be_null_for_create"
                elif mutation.operation == "create":
                    try:
                        student_payload = StudentCreate.model_validate(mutation.payload)
                    except ValidationError:
                        outcome["reason"] = "invalid_student_profile_payload"
                    else:
                        existing_student = conn.execute(
                            "SELECT organization_id FROM prototype_students WHERE student_id=?",
                            (mutation.entity_id,),
                        ).fetchone()
                        if existing_student is not None:
                            outcome["outcome"] = "conflict"
                            outcome["reason"] = "student_id_already_exists"
                        else:
                            student_values = student_payload.model_dump(mode="json")
                            conn.execute(
                                "INSERT INTO prototype_students (student_id, organization_id, branch_id, given_name, middle_name, family_name, date_of_birth, sex_at_registration, external_reference, status, version) VALUES (?,?,?,?,?,?,?,?,?,?,1)",
                                (mutation.entity_id, batch.organization_id, student_values["branch_id"],
                                 student_values["given_name"], student_values.get("middle_name"),
                                 student_values["family_name"], student_values.get("date_of_birth"),
                                 student_values["sex_at_registration"], student_values.get("external_reference"), "active"),
                            )
                            from app.services.student_store import _record_audit_event_conn
                            _record_audit_event_conn(conn, batch.organization_id, "student.created", "student", mutation.entity_id,
                                details={"source": "offline-sync", "version": 1}, actor_id=mutation.actor_id, source="offline-sync")
                            outcome["outcome"] = "accepted"
                            outcome["entity_id"] = mutation.entity_id
                            outcome["entity_version"] = 1
                elif mutation.operation == "update":
                    if mutation.base_version is None:
                        outcome["reason"] = "base_version_required_for_update"
                    else:
                        try:
                            student_update = StudentUpdate.model_validate(mutation.payload)
                        except ValidationError:
                            outcome["reason"] = "invalid_student_profile_update_payload"
                        else:
                            changes = student_update.model_dump(mode="json", exclude_unset=True)
                            if any(value is None for key, value in changes.items() if key in {"given_name", "family_name", "sex_at_registration"}):
                                outcome["reason"] = "required_student_fields_cannot_be_null"
                            else:
                                current = conn.execute(
                                    "SELECT * FROM prototype_students WHERE organization_id=? AND student_id=?",
                                    (batch.organization_id, mutation.entity_id),
                                ).fetchone()
                                if current is None:
                                    outcome["reason"] = "student_not_found_in_organization"
                                elif current["version"] != mutation.base_version:
                                    outcome["outcome"] = "conflict"
                                    outcome["reason"] = "base_version_mismatch"
                                    outcome["current_version"] = current["version"]
                                else:
                                    changed_fields = {key: value for key, value in changes.items() if current[key] != value}
                                    if not changed_fields:
                                        outcome["outcome"] = "accepted"
                                        outcome["entity_id"] = mutation.entity_id
                                        outcome["entity_version"] = current["version"]
                                        outcome["no_op"] = True
                                    else:
                                        assignments = ", ".join(f"{key}=?" for key in changed_fields)
                                        values = [*changed_fields.values(), batch.organization_id, mutation.entity_id, mutation.base_version]
                                        updated = conn.execute(
                                            f"UPDATE prototype_students SET {assignments}, version=version+1 WHERE organization_id=? AND student_id=? AND version=?",
                                            values,
                                        )
                                        if updated.rowcount != 1:
                                            raise RuntimeError("Student version changed while sync transaction held write lock")
                                        from app.services.student_store import _record_audit_event_conn
                                        _record_audit_event_conn(conn, batch.organization_id, "student.updated", "student", mutation.entity_id,
                                            details={"source": "offline-sync", "base_version": current["version"], "new_version": current["version"] + 1,
                                                     "changes": {key: {"from": current[key], "to": value} for key, value in changed_fields.items()}},
                                            actor_id=mutation.actor_id, source="offline-sync")
                                        outcome["outcome"] = "accepted"
                                        outcome["entity_id"] = mutation.entity_id
                                        outcome["entity_version"] = current["version"] + 1
                else:
                    outcome["reason"] = "unsupported_student_profile_operation"
            elif mutation.entity_type == "draft_assessment_result":
                if mutation.operation == "delete":
                    outcome["reason"] = "draft_assessment_result_delete_is_not_supported"
                elif mutation.operation == "create" and mutation.base_version is not None:
                    outcome["reason"] = "base_version_must_be_null_for_create"
                elif mutation.operation == "update" and mutation.base_version is None:
                    outcome["reason"] = "base_version_required_for_update"
                elif mutation.operation not in {"create", "update"}:
                    outcome["reason"] = "unsupported_draft_assessment_result_operation"
                else:
                    try:
                        allowed_result_keys = {"assessment_id", "student_id", "score", "comment"}
                        if set(mutation.payload) - allowed_result_keys:
                            raise ValueError("unknown result payload fields")
                        result_fields = {key: value for key, value in mutation.payload.items() if key != "assessment_id"}
                        if not isinstance(mutation.payload.get("assessment_id"), str) or not mutation.payload["assessment_id"].strip():
                            raise ValueError("assessment_id is required")
                        result_payload = ResultCreate.model_validate(result_fields)
                        score = str(result_payload.score)
                    except (ValidationError, ValueError):
                        outcome["reason"] = "invalid_draft_assessment_result_payload"
                    else:
                        assessment = conn.execute(
                            "SELECT status, max_score, section_id FROM prototype_assessments WHERE organization_id=? AND assessment_id=?",
                            (batch.organization_id, mutation.payload.get("assessment_id", "")),
                        ).fetchone()
                        if assessment is None:
                            outcome["reason"] = "assessment_not_found_in_organization"
                        elif assessment["status"] != "draft":
                            outcome["reason"] = "published_assessment_is_immutable"
                        else:
                            student = conn.execute(
                                "SELECT 1 FROM prototype_students WHERE organization_id=? AND student_id=?",
                                (batch.organization_id, result_payload.student_id),
                            ).fetchone()
                            if student is None:
                                outcome["reason"] = "student_not_found_in_organization"
                            elif Decimal(score) > Decimal(assessment["max_score"]):
                                outcome["reason"] = "score_exceeds_assessment_max_score"
                            else:
                                enrollment_ok = True
                                if assessment["section_id"]:
                                    enrollment_ok = conn.execute(
                                        "SELECT 1 FROM prototype_enrollments WHERE organization_id=? AND section_id=? AND student_id=? AND status='active'",
                                        (batch.organization_id, assessment["section_id"], result_payload.student_id),
                                    ).fetchone() is not None
                                if not enrollment_ok:
                                    outcome["reason"] = "student_not_enrolled_in_assessment_section"
                                else:
                                    current = conn.execute(
                                        "SELECT * FROM prototype_assessment_results WHERE organization_id=? AND assessment_id=? AND student_id=?",
                                        (batch.organization_id, mutation.payload.get("assessment_id", ""), result_payload.student_id),
                                    ).fetchone()
                                    if mutation.operation == "create" and current is not None:
                                        outcome["outcome"] = "conflict"
                                        outcome["reason"] = "assessment_result_already_exists"
                                    elif mutation.operation == "update" and current is None:
                                        outcome["reason"] = "assessment_result_not_found"
                                    elif mutation.operation == "update" and current["result_id"] != mutation.entity_id:
                                        outcome["outcome"] = "conflict"
                                        outcome["reason"] = "result_id_mismatch"
                                    elif mutation.operation == "update" and current["version"] != mutation.base_version:
                                        outcome["outcome"] = "conflict"
                                        outcome["reason"] = "base_version_mismatch"
                                        outcome["current_version"] = current["version"]
                                    elif mutation.operation == "create" and conn.execute(
                                        "SELECT 1 FROM prototype_assessment_results WHERE organization_id=? AND result_id=?",
                                        (batch.organization_id, mutation.entity_id),
                                    ).fetchone():
                                        outcome["outcome"] = "conflict"
                                        outcome["reason"] = "result_id_already_exists"
                                    else:
                                        import uuid as _uuid
                                        comment = result_payload.comment
                                        if current is None:
                                            conn.execute(
                                                "INSERT INTO prototype_assessment_results (result_id, organization_id, assessment_id, student_id, score, comment, version) VALUES (?,?,?,?,?,?,1)",
                                                (mutation.entity_id, batch.organization_id, mutation.payload["assessment_id"], result_payload.student_id, score, comment),
                                            )
                                            change_type, old_score, old_comment, new_version = "created", None, None, 1
                                        else:
                                            conn.execute(
                                                "UPDATE prototype_assessment_results SET score=?, comment=?, version=version+1, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE organization_id=? AND assessment_id=? AND student_id=? AND version=?",
                                                (score, comment, batch.organization_id, mutation.payload["assessment_id"], result_payload.student_id, mutation.base_version),
                                            )
                                            change_type, old_score, old_comment, new_version = "updated", current["score"], current["comment"], current["version"] + 1
                                        conn.execute(
                                            "INSERT INTO prototype_assessment_result_history (history_id, organization_id, assessment_id, student_id, change_type, previous_score, previous_comment, new_score, new_comment) VALUES (?,?,?,?,?,?,?,?,?)",
                                            (str(_uuid.uuid4()), batch.organization_id, mutation.payload["assessment_id"], result_payload.student_id, change_type, old_score, old_comment, score, comment),
                                        )
                                        outcome.update({"outcome": "accepted", "entity_id": mutation.entity_id, "entity_version": new_version})
            elif mutation.entity_type != "attendance_record":
                outcome["reason"] = "only_student_create_update_draft_assessment_result_and_attendance_mutations_are_supported"
            elif mutation.operation == "create":
                try:
                    attendance = AttendanceCreate.model_validate(mutation.payload)
                except ValidationError:
                    outcome["reason"] = "invalid_attendance_payload"
                else:
                    student = conn.execute(
                        "SELECT branch_id FROM prototype_students WHERE organization_id=? AND student_id=?",
                        (batch.organization_id, attendance.student_id),
                    ).fetchone()
                    if student is None:
                        outcome["reason"] = "student_not_found_in_organization"
                    else:
                        existing = conn.execute(
                            "SELECT attendance_id FROM prototype_attendance WHERE organization_id=? AND student_id=? AND attendance_date=?",
                            (batch.organization_id, attendance.student_id, attendance.attendance_date.isoformat()),
                        ).fetchone()
                        entity_existing = conn.execute(
                            "SELECT attendance_id FROM prototype_attendance WHERE organization_id=? AND attendance_id=?",
                            (batch.organization_id, mutation.entity_id),
                        ).fetchone()
                        if existing or entity_existing:
                            outcome["outcome"] = "conflict"
                            outcome["reason"] = "attendance_already_exists_or_entity_id_reused"
                        else:
                            conn.execute(
                                "INSERT INTO prototype_attendance (attendance_id, organization_id, branch_id, student_id, attendance_date, status, note, version) VALUES (?,?,?,?,?,?,?,1)",
                                (mutation.entity_id, batch.organization_id, student["branch_id"], attendance.student_id, attendance.attendance_date.isoformat(), attendance.status.value, attendance.note),
                            )
                            outcome["outcome"] = "accepted"
                            outcome["entity_id"] = mutation.entity_id
                            outcome["entity_version"] = 1
            elif mutation.operation == "update":
                if mutation.base_version is None:
                    outcome["reason"] = "base_version_required_for_update"
                else:
                    try:
                        correction = AttendanceUpdate.model_validate(mutation.payload)
                    except ValidationError:
                        outcome["reason"] = "invalid_attendance_update_payload"
                    else:
                        current = conn.execute(
                            "SELECT status, note, version FROM prototype_attendance WHERE organization_id=? AND attendance_id=?",
                            (batch.organization_id, mutation.entity_id),
                        ).fetchone()
                        if current is None:
                            outcome["reason"] = "attendance_not_found_in_organization"
                        elif current["version"] != mutation.base_version:
                            outcome["outcome"] = "conflict"
                            outcome["reason"] = "base_version_mismatch"
                            outcome["current_version"] = current["version"]
                        else:
                            import uuid
                            conn.execute(
                                "INSERT INTO prototype_attendance_changes (change_id, organization_id, attendance_id, old_status, new_status, reason) VALUES (?,?,?,?,?,?)",
                                (str(uuid.uuid4()), batch.organization_id, mutation.entity_id, current["status"], correction.status.value, correction.reason),
                            )
                            updated = conn.execute(
                                "UPDATE prototype_attendance SET status=?, note=?, version=version+1, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE organization_id=? AND attendance_id=? AND version=?",
                                (correction.status.value, correction.note, batch.organization_id, mutation.entity_id, mutation.base_version),
                            )
                            if updated.rowcount != 1:
                                # The write lock should prevent this; fail closed if assumptions change.
                                raise RuntimeError("Attendance version changed while sync transaction held write lock")
                            outcome["outcome"] = "accepted"
                            outcome["entity_id"] = mutation.entity_id
                            outcome["entity_version"] = mutation.base_version + 1
            else:
                outcome["reason"] = "attendance_delete_is_not_supported"
            conn.execute(
                "INSERT INTO prototype_sync_outcomes (organization_id, mutation_id, device_id, actor_id, request_hash, outcome_json) VALUES (?,?,?,?,?,?)",
                (batch.organization_id, mutation.mutation_id, batch.device_id, mutation.actor_id, digest,
                 json.dumps(outcome, sort_keys=True, separators=(",", ":"))),
            )
            results.append(outcome)
    applied = any(item.get("outcome") == "accepted" for item in results)
    return {"protocol_version": 1, "organization_id": batch.organization_id, "device_id": batch.device_id, "items": results,
            "mode": "student-attendance-draft-assessment-result-mutations-prototype", "business_mutations_applied": applied}
