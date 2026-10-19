"""Development-only assessment and results API; organization header is not authentication."""
from decimal import Decimal
from fastapi import APIRouter, Header, HTTPException, Response, status
from app.schemas.academics import AssessmentCreate, ResultCreate
from app.services import student_store

router = APIRouter(prefix="/api/v1/academics", tags=["academics"])


def _org(value: str | None) -> str:
    if not value or not value.strip() or len(value.strip()) > 64:
        raise HTTPException(status_code=400, detail="A valid X-Organization-ID header is required")
    return value.strip()


@router.post("/assessments", status_code=status.HTTP_201_CREATED, summary="Create a draft assessment")
def create_assessment(payload: AssessmentCreate, response: Response, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    data = payload.model_dump(mode="json")
    data["organization_id"] = _org(organization_id)
    try:
        result = student_store.create_assessment(data)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=f"Unknown organization-scoped {error.args[0]}")
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    response.headers["X-Prototype-Only"] = "true"
    return result


@router.get("/assessments", summary="List assessments")
def get_assessments(branch_id: str | None = None, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    return {"items": student_store.list_assessments(_org(organization_id), branch_id), "prototype_only": True}


@router.get("/students", summary="List active students in a branch for result entry")
def get_students(branch_id: str, section_id: str | None = None, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    return {"items": student_store.list_students_for_assessment(_org(organization_id), branch_id, section_id), "prototype_only": True}


@router.post("/assessments/{assessment_id}/results", summary="Save or update a draft student result")
def save_result(assessment_id: str, payload: ResultCreate, response: Response, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    org = _org(organization_id)
    try:
        result = student_store.save_assessment_result(org, assessment_id, payload.student_id, str(payload.score), payload.comment)
    except PermissionError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=f"Student not found in this organization: {error.args[0]}")
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    if result is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    response.headers["X-Prototype-Only"] = "true"
    return result


@router.get("/assessments/{assessment_id}/results", summary="List results for an assessment")
def get_results(assessment_id: str, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    result = student_store.list_assessment_results(_org(organization_id), assessment_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return {"items": result, "total": len(result), "prototype_only": True}


@router.get("/assessments/{assessment_id}/results/{student_id}/history", summary="View score edit history for a student")
def get_result_history(assessment_id: str, student_id: str, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    history = student_store.list_assessment_result_history(_org(organization_id), assessment_id, student_id)
    if history is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return {"items": history, "total": len(history), "prototype_only": True}


@router.post("/assessments/{assessment_id}/publish", summary="Publish assessment results and lock edits")
def publish_results(assessment_id: str, response: Response, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    try:
        result = student_store.publish_assessment(_org(organization_id), assessment_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    if result is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    response.headers["X-Prototype-Only"] = "true"
    return result


@router.get("/reports/students/{student_id}", summary="Build a report-card view from published assessments")
def get_student_report_card(
    student_id: str,
    section_id: str,
    term: str,
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
):
    if not section_id.strip() or not term.strip():
        raise HTTPException(status_code=422, detail="section_id and term are required")
    report = student_store.build_student_report_card(_org(organization_id), student_id, section_id.strip(), term.strip())
    if report is None:
        raise HTTPException(status_code=404, detail="Active student enrollment not found in this organization and section")
    return report
