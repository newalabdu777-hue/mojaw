"""Development-only academic year, class, section and enrollment endpoints."""
import sqlite3
from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from app.schemas.classrooms import AcademicYearCreate, ClassLevelCreate, SectionCreate, EnrollmentCreate
from app.services import student_store

router = APIRouter(prefix="/api/v1/classrooms", tags=["classrooms"])


def _org(value: str | None) -> str:
    if not value or not value.strip() or len(value.strip()) > 64:
        raise HTTPException(status_code=400, detail="A valid X-Organization-ID header is required")
    return value.strip()


def _conflict(error: sqlite3.IntegrityError) -> HTTPException:
    return HTTPException(status_code=409, detail="A record conflicts with an existing record or references an unknown organization-scoped record")


@router.post("/academic-years", status_code=status.HTTP_201_CREATED)
def create_year(payload: AcademicYearCreate, response: Response, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    try:
        item = student_store.create_academic_year({**payload.model_dump(mode="json"), "organization_id": _org(organization_id)})
    except sqlite3.IntegrityError as error:
        raise _conflict(error)
    response.headers["X-Prototype-Only"] = "true"
    return item


@router.get("/academic-years")
def get_years(organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    return {"items": student_store.list_academic_years(_org(organization_id)), "prototype_only": True}


@router.post("/class-levels", status_code=status.HTTP_201_CREATED)
def create_level(payload: ClassLevelCreate, response: Response, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    try:
        item = student_store.create_class_level({**payload.model_dump(), "organization_id": _org(organization_id)})
    except sqlite3.IntegrityError as error:
        raise _conflict(error)
    response.headers["X-Prototype-Only"] = "true"
    return item


@router.get("/class-levels")
def get_levels(organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    return {"items": student_store.list_class_levels(_org(organization_id)), "prototype_only": True}


@router.post("/sections", status_code=status.HTTP_201_CREATED)
def create_section(payload: SectionCreate, response: Response, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    try:
        item = student_store.create_section({**payload.model_dump(), "organization_id": _org(organization_id)})
    except sqlite3.IntegrityError as error:
        raise _conflict(error)
    response.headers["X-Prototype-Only"] = "true"
    return item


@router.get("/sections")
def get_sections(branch_id: str | None = Query(default=None, max_length=64), year_id: str | None = Query(default=None, max_length=64), organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    return {"items": student_store.list_sections(_org(organization_id), branch_id, year_id), "prototype_only": True}


@router.get("/sections/{section_id}/students", summary="List active enrolled students for a section")
def get_section_students(section_id: str, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    items = student_store.list_students_for_section(_org(organization_id), section_id)
    if items is None:
        raise HTTPException(status_code=404, detail="Section not found")
    return {"items": items, "total": len(items), "prototype_only": True}


@router.post("/enrollments", status_code=status.HTTP_201_CREATED)
def create_enrollment(payload: EnrollmentCreate, response: Response, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    try:
        item = student_store.create_enrollment(_org(organization_id), payload.student_id, payload.section_id, payload.enrolled_on.isoformat())
    except LookupError as error:
        raise HTTPException(status_code=404, detail=f"Unknown organization-scoped {error.args[0]}")
    except OverflowError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Student already has an active enrollment or enrollment violates a constraint")
    response.headers["X-Prototype-Only"] = "true"
    return item


@router.get("/enrollments")
def get_enrollments(section_id: str | None = Query(default=None, max_length=64), enrollment_status: str | None = Query(default=None, alias="status", pattern="^(active|completed|withdrawn)$"), organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    return {"items": student_store.list_enrollments(_org(organization_id), section_id, enrollment_status), "prototype_only": True}
