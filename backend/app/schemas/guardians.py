"""Development-only guardian request/response contracts."""
from pydantic import BaseModel, ConfigDict, StringConstraints
from typing import Annotated

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Contact = Annotated[str, StringConstraints(strip_whitespace=True, max_length=160)]

class GuardianCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    given_name: Text
    family_name: Text
    relationship: Text
    phone: Contact | None = None
    email: Contact | None = None
    is_primary: bool = False

class GuardianResponse(BaseModel):
    guardian_id: str
    organization_id: str
    student_id: str
    given_name: str
    family_name: str
    relationship: str
    phone: str | None = None
    email: str | None = None
    is_primary: bool
    portal_access: bool = False
    created_at: str

class GuardianLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relationship: Text
    is_primary: bool = False
