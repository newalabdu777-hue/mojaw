"""Contracts for the disposable finance API prototype. Amounts are integer minor units."""
from datetime import date
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BillCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    student_id: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=200)
    amount_minor: int = Field(gt=0, le=9_000_000_000_000_000)
    currency: str = Field(default="ETB", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    due_date: date | None = None

    @field_validator("student_id", "description")
    @classmethod
    def trim_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field cannot be blank")
        return value


class PaymentAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bill_id: str = Field(min_length=1, max_length=64)
    amount_minor: int = Field(gt=0, le=9_000_000_000_000_000)


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    student_id: str = Field(min_length=1, max_length=64)
    amount_minor: int = Field(gt=0, le=9_000_000_000_000_000)
    currency: str = Field(default="ETB", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    allocations: list[PaymentAllocation] = Field(default_factory=list, max_length=100)
    payment_method: str = Field(default="cash", pattern=r"^(cash|bank_transfer|card|mobile_money|other)$")
    note: str | None = Field(default=None, max_length=500)

    @field_validator("student_id")
    @classmethod
    def trim_student(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("student_id cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_allocations(self):
        ids = [item.bill_id for item in self.allocations]
        if len(ids) != len(set(ids)):
            raise ValueError("Each bill may appear only once in allocations")
        if sum(item.amount_minor for item in self.allocations) > self.amount_minor:
            raise ValueError("Allocated amount cannot exceed payment amount")
        return self


class LedgerAccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=120)
    account_type: str = Field(pattern=r"^(asset|liability|equity|revenue|expense)$")
    currency: str = Field(default="ETB", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")

    @field_validator("code", "name")
    @classmethod
    def trim_ledger_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field cannot be blank")
        return value


class LedgerLineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str = Field(min_length=1, max_length=64)
    debit_minor: int = Field(default=0, ge=0, le=9_000_000_000_000_000)
    credit_minor: int = Field(default=0, ge=0, le=9_000_000_000_000_000)

    @model_validator(mode="after")
    def one_side_only(self):
        if (self.debit_minor > 0) == (self.credit_minor > 0):
            raise ValueError("Each line must have exactly one positive debit or credit")
        return self


class LedgerJournalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1, max_length=240)
    currency: str = Field(default="ETB", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    lines: list[LedgerLineCreate] = Field(min_length=2, max_length=100)

    @field_validator("description")
    @classmethod
    def trim_journal_description(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("description cannot be blank")
        return value

    @model_validator(mode="after")
    def balanced_and_distinct(self):
        if sum(line.debit_minor for line in self.lines) != sum(line.credit_minor for line in self.lines):
            raise ValueError("Journal entry debits must equal credits")
        if sum(line.debit_minor for line in self.lines) <= 0:
            raise ValueError("Journal entry total must be greater than zero")
        if len({line.account_id for line in self.lines}) < 2:
            raise ValueError("A journal entry must affect at least two different accounts")
        return self


class LedgerJournalReverse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A reversal reason is required")
        return value
