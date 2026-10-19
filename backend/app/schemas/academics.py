"""Academic assessment contracts for the disposable development prototype."""
from datetime import date
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AssessmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branch_id: str = Field(min_length=1, max_length=64)
    section_id: str | None = Field(default=None, max_length=64)
    subject: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=160)
    term: str = Field(min_length=1, max_length=80)
    assessment_date: date | None = None
    max_score: Decimal = Field(gt=0, max_digits=8, decimal_places=3)

    @field_validator("branch_id", "subject", "title", "term")
    @classmethod
    def trim_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field cannot be blank")
        return value


class ResultCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    student_id: str = Field(min_length=1, max_length=64)
    score: Decimal = Field(ge=0, max_digits=8, decimal_places=3)
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("student_id")
    @classmethod
    def trim_student(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("student_id cannot be blank")
        return value
