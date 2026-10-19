"""Development-only student endpoints. Organization header is not authentication."""
from datetime import date
from uuid import uuid4
from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.students import StudentCreate, StudentUpdate, SexAtRegistration
from app.services import student_store

router = APIRouter(prefix="/api/v1/students", tags=["students"],
                   responses={400: {"description": "Invalid request"}})


class StudentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    student_id: str
    organization_id: str
    branch_id: str
    given_name: str
    middle_name: str | None = None
    family_name: str
    date_of_birth: date | None = None
    sex_at_registration: SexAtRegistration
    external_reference: str | None = None
    status: str
    created_at: str


class StudentListResponse(BaseModel):
    items: list[StudentResponse]
    total: int
    limit: int
    offset: int


class StudentDeactivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=500, description="Required reason retained in the audit trail")


def _organization(value: str | None) -> str:
    if not value or not value.strip():
        raise HTTPException(status_code=400, detail="X-Organization-ID header is required")
    if len(value.strip()) > 64:
        raise HTTPException(status_code=400, detail="X-Organization-ID must be at most 64 characters")
    return value.strip()


@router.get("", response_model=StudentListResponse, summary="List students in a development organization")
def list_students(
    branch_id: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=120, description="Case-insensitive substring search across student names, external reference, and ID"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
) -> StudentListResponse:
    org = _organization(organization_id)
    items, total = student_store.list_students(org, branch_id, limit, offset, q)
    return StudentListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=StudentResponse, status_code=status.HTTP_201_CREATED,
             summary="Create a development student record")
def create_student(
    payload: StudentCreate,
    response: Response,
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
) -> StudentResponse:
    org = _organization(organization_id)
    item = payload.model_dump(mode="json")
    item.update(student_id=str(uuid4()), organization_id=org, status="active")
    created = student_store.create_student(item)
    response.headers["X-Prototype-Only"] = "true"
    return StudentResponse(**created)


@router.get("/{student_id}/history", summary="Read a student record's audit history")
def get_student_history(
    student_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
):
    org = _organization(organization_id)
    # Verify the student belongs to this organization before exposing history.
    if student_store.get_student(org, student_id) is None:
        raise HTTPException(status_code=404, detail="Student not found")
    result = student_store.list_audit_events(
        org, entity_type="student", entity_id=student_id, limit=limit, offset=offset
    )
    result["student_id"] = student_id
    return result


@router.get("/{student_id}", response_model=StudentResponse, summary="Get one student in a development organization")
def get_student(
    student_id: str,
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
) -> StudentResponse:
    org = _organization(organization_id)
    item = student_store.get_student(org, student_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return StudentResponse(**item)


@router.patch("/{student_id}", response_model=StudentResponse, summary="Update editable fields of a development student")
def patch_student(
    student_id: str,
    payload: StudentUpdate,
    response: Response,
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
) -> StudentResponse:
    org = _organization(organization_id)
    changes = payload.model_dump(mode="json", exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one field must be provided")
    if any(value is None for key, value in changes.items() if key in {"given_name", "family_name", "sex_at_registration"}):
        raise HTTPException(status_code=422, detail="Required fields cannot be set to null")
    item = student_store.update_student(org, student_id, changes)
    if item is None:
        raise HTTPException(status_code=404, detail="Student not found")
    response.headers["X-Prototype-Only"] = "true"
    return StudentResponse(**item)


@router.post("/{student_id}/deactivate", response_model=StudentResponse,
             summary="Deactivate a student with an audited reason")
def deactivate_student(
    student_id: str,
    payload: StudentDeactivationRequest,
    response: Response,
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
) -> StudentResponse:
    org = _organization(organization_id)
    reason = payload.reason.strip()
    if len(reason) < 3:
        raise HTTPException(status_code=422, detail="Reason must contain at least 3 non-whitespace characters")
    item, changed = student_store.deactivate_student(org, student_id, reason)
    if item is None:
        raise HTTPException(status_code=404, detail="Student not found")
    if not changed:
        raise HTTPException(status_code=409, detail="Student is already inactive")
    response.headers["X-Prototype-Only"] = "true"
    return StudentResponse(**item)
