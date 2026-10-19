"""Development-only student/guardian links; organization header is not authentication."""
from fastapi import APIRouter, Header, HTTPException, Query, Response, status
import sqlite3
from app.schemas.guardians import GuardianCreate, GuardianLinkCreate, GuardianResponse
from app.services import student_store

router = APIRouter(prefix="/api/v1/students/{student_id}/guardians", tags=["guardians"])

def _org(value: str | None) -> str:
    if not value or not value.strip() or len(value.strip()) > 64:
        raise HTTPException(status_code=400, detail="A valid X-Organization-ID header is required")
    return value.strip()

@router.get("", response_model=list[GuardianResponse], summary="List guardians linked to a student")
def get_guardians(student_id: str, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    result = student_store.list_guardians(_org(organization_id), student_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return result

@router.post("", response_model=GuardianResponse, status_code=status.HTTP_201_CREATED, summary="Link a new guardian to a student")
def create_guardian(student_id: str, payload: GuardianCreate, response: Response, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    result = student_store.add_guardian(_org(organization_id), student_id, payload.model_dump())
    if result is None:
        raise HTTPException(status_code=404, detail="Student not found")
    response.headers["X-Prototype-Only"] = "true"
    return result


@router.post("/{guardian_id}/link", response_model=GuardianResponse, status_code=status.HTTP_201_CREATED, summary="Link an existing guardian identity to another student")
def link_existing_guardian(student_id: str, guardian_id: str, payload: GuardianLinkCreate, response: Response, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    org = _org(organization_id)
    try:
        result = student_store.link_existing_guardian(org, student_id, guardian_id, payload.relationship, payload.is_primary)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="This guardian is already linked to this student")
    if result is None:
        raise HTTPException(status_code=404, detail="Student or guardian not found in this organization")
    response.headers["X-Prototype-Only"] = "true"
    return result


# Separate organization-scoped directory route used to find an existing shared guardian identity.
directory_router = APIRouter(prefix="/api/v1/guardians", tags=["guardians"])

@directory_router.get("", summary="Search guardian identities within the current organization")
def search_guardian_directory(
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
):
    return student_store.search_guardian_directory(_org(organization_id), q, limit, offset)
