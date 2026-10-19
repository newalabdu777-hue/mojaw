"""Attendance API contracts for the disposable development prototype."""
from datetime import date
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AttendanceStatus(str, Enum):
    present = "present"
    absent = "absent"
    late = "late"
    excused = "excused"


class AttendanceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    student_id: str = Field(min_length=1, max_length=64)
    attendance_date: date
    status: AttendanceStatus
    note: str | None = Field(default=None, max_length=500)

    @field_validator("student_id")
    @classmethod
    def clean_student_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("student_id cannot be blank")
        return value


class AttendanceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: AttendanceStatus
    reason: str = Field(min_length=3, max_length=500)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("A meaningful correction reason is required")
        return value


class AttendanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    attendance_id: str
    organization_id: str
    branch_id: str
    student_id: str
    attendance_date: date
    status: AttendanceStatus
    note: str | None = None
    created_at: str
    updated_at: str
    version: int = Field(default=1, ge=1)


class AttendanceBulkItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    student_id: str = Field(min_length=1, max_length=64)
    status: AttendanceStatus
    note: str | None = Field(default=None, max_length=500)

    @field_validator("student_id")
    @classmethod
    def clean_student_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("student_id cannot be blank")
        return value


class AttendanceBulkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attendance_date: date
    records: list[AttendanceBulkItem] = Field(min_length=1, max_length=500)

    @field_validator("records")
    @classmethod
    def unique_students(cls, records: list[AttendanceBulkItem]) -> list[AttendanceBulkItem]:
        ids = [record.student_id for record in records]
        if len(ids) != len(set(ids)):
            raise ValueError("Each student may appear only once in a bulk attendance request")
        return records
