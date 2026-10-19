"""Student API contract DTOs only; persistence waits for approved schema."""
from datetime import date
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from typing import Annotated

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class SexAtRegistration(StrEnum):
    FEMALE = "female"
    MALE = "male"
    UNSPECIFIED = "unspecified"


class StudentCreate(BaseModel):
    """Request shape for student registration; admission number is server-assigned."""
    model_config = ConfigDict(extra="forbid")

    given_name: NonEmptyText
    middle_name: NonEmptyText | None = None
    family_name: NonEmptyText
    date_of_birth: date | None = None
    sex_at_registration: SexAtRegistration = SexAtRegistration.UNSPECIFIED
    branch_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    external_reference: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None


class StudentSummary(BaseModel):
    """Response shape reserved for persisted student records."""
    student_id: str
    admission_number: str
    given_name: str
    middle_name: str | None = None
    family_name: str
    branch_id: str
    status: str = "active"


class StudentUpdate(BaseModel):
    """Partial update contract; branch changes require a separate transfer workflow."""
    model_config = ConfigDict(extra="forbid")

    given_name: NonEmptyText | None = None
    middle_name: NonEmptyText | None = None
    family_name: NonEmptyText | None = None
    date_of_birth: date | None = None
    sex_at_registration: SexAtRegistration | None = None
    external_reference: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None

    @model_validator(mode="after")
    def require_at_least_one_field(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self
