"""Development-only attendance API. Organization header is not authentication."""
import csv
import io
import sqlite3
from datetime import date
from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from app.schemas.attendance import AttendanceBulkCreate, AttendanceCreate, AttendanceResponse, AttendanceUpdate
from app.services import student_store

router = APIRouter(prefix="/api/v1/attendance", tags=["attendance"])


def _org(value: str | None) -> str:
    if not value or not value.strip() or len(value.strip()) > 64:
        raise HTTPException(status_code=400, detail="A valid X-Organization-ID header is required")
    return value.strip()


@router.post("", response_model=AttendanceResponse, status_code=status.HTTP_201_CREATED, summary="Record attendance for one student and date")
def create_record(payload: AttendanceCreate, response: Response, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    org = _org(organization_id)
    try:
        record = payload.model_dump(mode="json")
        record["organization_id"] = org
        result = student_store.create_attendance(record)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Attendance already exists for this student and date")
    if result is None:
        raise HTTPException(status_code=404, detail="Student not found in this organization")
    response.headers["X-Prototype-Only"] = "true"
    return result


@router.post("/bulk", status_code=status.HTTP_201_CREATED, summary="Record attendance for a class atomically")
def create_bulk_records(payload: AttendanceBulkCreate, response: Response, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    org = _org(organization_id)
    records = [item.model_dump(mode="json") for item in payload.records]
    try:
        created = student_store.create_attendance_bulk(org, payload.attendance_date.isoformat(), records)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="At least one attendance record already exists; no records were created")
    except LookupError as error:
        raise HTTPException(status_code=404, detail=f"Student not found in this organization: {error.args[0]}; no records were created")
    response.headers["X-Prototype-Only"] = "true"
    return {"items": created, "created": len(created), "attendance_date": payload.attendance_date.isoformat(), "prototype_only": True}


@router.post("/sections/{section_id}/bulk", status_code=status.HTTP_201_CREATED, summary="Record attendance for currently enrolled students in one section")
def create_section_bulk_records(section_id: str, payload: AttendanceBulkCreate, response: Response, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    org = _org(organization_id)
    records = [item.model_dump(mode="json") for item in payload.records]
    try:
        created = student_store.create_section_attendance_bulk(org, section_id, payload.attendance_date.isoformat(), records)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="At least one attendance record already exists; no records were created")
    except LookupError as error:
        raise HTTPException(status_code=404, detail=f"Section or enrolled student not found: {error.args[0]}; no records were created")
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    response.headers["X-Prototype-Only"] = "true"
    return {"items": created, "created": len(created), "section_id": section_id, "attendance_date": payload.attendance_date.isoformat(), "prototype_only": True}


@router.get("", summary="List attendance records within the organization")
def get_records(
    attendance_date: date | None = Query(default=None),
    branch_id: str | None = Query(default=None, max_length=64),
    student_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
):
    items, total = student_store.list_attendance(_org(organization_id), attendance_date.isoformat() if attendance_date else None, branch_id, student_id, limit, offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/reports/students", summary="Report recorded attendance counts per active student")
def get_student_attendance_report(
    start_date: date = Query(...),
    end_date: date = Query(...),
    branch_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
):
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
    result = student_store.attendance_student_report(
        _org(organization_id), start_date.isoformat(), end_date.isoformat(), branch_id, limit, offset
    )
    result["prototype_only"] = True
    return result


def _csv_safe(value: object) -> str:
    """Prevent spreadsheet formula execution when opening exported text in Excel-like apps."""
    text = "" if value is None else str(value)
    probe = text.lstrip(" \t\r\n")
    if probe.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


@router.get("/reports/students.csv", summary="Export a paginated student attendance report as CSV")
def export_student_attendance_report_csv(
    start_date: date = Query(...),
    end_date: date = Query(...),
    branch_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
):
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
    report = student_store.attendance_student_report(
        _org(organization_id), start_date.isoformat(), end_date.isoformat(), branch_id, limit, offset
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow([
        "student_id", "branch_id", "full_name", "total_recorded", "present", "absent",
        "late", "excused", "attendance_rate_pct",
    ])
    for item in report["items"]:
        writer.writerow([_csv_safe(item.get(key)) for key in (
            "student_id", "branch_id", "full_name", "total_recorded", "present", "absent",
            "late", "excused", "attendance_rate_pct",
        )])
    content = output.getvalue()
    output.close()
    response = StreamingResponse(iter([content]), media_type="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = (
        f'attachment; filename="student-attendance-{start_date.isoformat()}-{end_date.isoformat()}.csv"'
    )
    response.headers["X-Prototype-Only"] = "true"
    response.headers["X-Report-Total"] = str(report["total"])
    response.headers["X-Report-Exported"] = str(len(report["items"]))
    return response


@router.get("/summary", summary="Summarize recorded attendance for a date range")
def get_summary(
    start_date: date = Query(...),
    end_date: date = Query(...),
    branch_id: str | None = Query(default=None, max_length=64),
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
):
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
    result = student_store.attendance_summary(
        _org(organization_id), start_date.isoformat(), end_date.isoformat(), branch_id
    )
    result["prototype_only"] = True
    return result


@router.patch("/{attendance_id}", response_model=AttendanceResponse, summary="Correct attendance with a required reason")
def correct_record(attendance_id: str, payload: AttendanceUpdate, response: Response, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    org = _org(organization_id)
    result = student_store.update_attendance(org, attendance_id, payload.status.value, payload.note, payload.reason)
    if result is None:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    response.headers["X-Prototype-Only"] = "true"
    return result


@router.get("/{attendance_id}/history", summary="View correction history for an attendance record")
def get_history(attendance_id: str, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    result = student_store.attendance_history(_org(organization_id), attendance_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    return {"items": result, "total": len(result)}
