"""Contracts for the disposable classroom-management prototype."""
from datetime import date
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator


class AcademicYearCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    start_date: date
    end_date: date

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank")
        return value

    @model_validator(mode="after")
    def dates_in_order(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class ClassLevelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    sort_order: int = Field(default=0, ge=0, le=10000)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank")
        return value


class SectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branch_id: str = Field(min_length=1, max_length=64)
    year_id: str = Field(min_length=1, max_length=64)
    level_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=80)
    capacity: int | None = Field(default=None, gt=0, le=1000)

    @field_validator("branch_id", "year_id", "level_id", "name")
    @classmethod
    def trim_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field cannot be blank")
        return value


class EnrollmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    student_id: str = Field(min_length=1, max_length=64)
    section_id: str = Field(min_length=1, max_length=64)
    enrolled_on: date

    @field_validator("student_id", "section_id")
    @classmethod
    def trim_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field cannot be blank")
        return value
