"""Development-only fee billing and provisional payment API."""
import sqlite3
from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from app.schemas.finance import BillCreate, PaymentCreate, LedgerAccountCreate, LedgerJournalCreate, LedgerJournalReverse
from app.services import student_store

router = APIRouter(prefix="/api/v1/finance", tags=["finance-prototype"])


def _org(value: str | None) -> str:
    if not value or not value.strip() or len(value.strip()) > 64:
        raise HTTPException(status_code=400, detail="A valid X-Organization-ID header is required")
    return value.strip()


def _idempotency_key(value: str | None) -> str | None:
    """Normalize and validate client retry keys consistently across finance writes."""
    if value is None:
        return None
    key = value.strip()
    if not key or len(key) > 128:
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key must contain 1 to 128 non-whitespace characters",
        )
    return key


@router.get("/audit-events", summary="Browse append-only finance audit events")
def get_audit_events(
    entity_type: str | None = None,
    entity_id: str | None = None,
    event_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
):
    return student_store.list_audit_events(_org(organization_id), entity_type, entity_id, event_type, limit, offset)


@router.post("/bills", status_code=status.HTTP_201_CREATED, summary="Create a student fee bill")
def create_bill(
    payload: BillCreate, response: Response,
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    idempotency_key = _idempotency_key(idempotency_key)
    try:
        result = student_store.create_fee_bill(_org(organization_id), payload.model_dump(mode="json"), idempotency_key)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=f"Unknown organization-scoped {error.args[0]}")
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Bill conflicts with a stored record")
    response.headers["X-Prototype-Only"] = "true"
    return result


@router.get("/bills", summary="List student fee bills and remaining balances")
def get_bills(student_id: str | None = None, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    return {"items": student_store.list_fee_bills(_org(organization_id), student_id), "prototype_only": True}


@router.post("/payments", status_code=status.HTTP_201_CREATED, summary="Record a provisional payment with manual bill allocations")
def create_payment(
    payload: PaymentCreate, response: Response,
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    idempotency_key = _idempotency_key(idempotency_key)
    data = payload.model_dump(mode="json")
    try:
        result = student_store.create_fee_payment(_org(organization_id), data, idempotency_key)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=f"Unknown organization-scoped {error.args[0]}")
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Payment conflicts with a stored record")
    response.headers["X-Prototype-Only"] = "true"
    return result


@router.get("/payments", summary="List provisional and reconciled payments")
def get_payments(student_id: str | None = None, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    return {"items": student_store.list_fee_payments(_org(organization_id), student_id), "prototype_only": True}


@router.post("/payments/{payment_id}/reconcile", summary="Reconcile a provisional payment (prototype only)")
def reconcile_payment(payment_id: str, response: Response, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    try:
        result = student_store.reconcile_fee_payment(_org(organization_id), payment_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    if result is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    response.headers["X-Prototype-Only"] = "true"
    return result


@router.get("/students/{student_id}/account", summary="Summarize the append-only student fee journal")
def get_student_account(student_id: str, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    result = student_store.student_account_summary(_org(organization_id), student_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return result


@router.get("/students/{student_id}/statement", summary="Read a detailed student fee statement")
def get_student_statement(
    student_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
):
    result = student_store.student_account_statement(_org(organization_id), student_id, limit, offset)
    if result is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return result


@router.post("/ledger/accounts", status_code=status.HTTP_201_CREATED, summary="Create a general-ledger account (prototype only)")
def create_ledger_account(payload: LedgerAccountCreate, response: Response, organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    try:
        result = student_store.create_ledger_account(_org(organization_id), payload.model_dump(mode="json"))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Account code already exists in this organization")
    response.headers["X-Prototype-Only"] = "true"
    return result


@router.get("/ledger/accounts", summary="List general-ledger accounts")
def get_ledger_accounts(organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    return {"items": student_store.list_ledger_accounts(_org(organization_id)), "prototype_only": True}


@router.post("/ledger/journals", status_code=status.HTTP_201_CREATED, summary="Post a balanced general-ledger journal")
def post_ledger_journal(
    payload: LedgerJournalCreate,
    response: Response,
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    idempotency_key = _idempotency_key(idempotency_key)
    try:
        result = student_store.post_ledger_journal(_org(organization_id), payload.model_dump(mode="json"), idempotency_key)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=f"Unknown organization-scoped {error.args[0]}")
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Journal conflicts with a stored record")
    response.headers["X-Prototype-Only"] = "true"
    return result


@router.post("/ledger/journals/{journal_id}/reverse", status_code=status.HTTP_201_CREATED, summary="Reverse a posted journal without editing its history")
def reverse_ledger_journal(
    journal_id: str,
    payload: LedgerJournalReverse,
    response: Response,
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
):
    try:
        result = student_store.reverse_ledger_journal(_org(organization_id), journal_id, payload.reason)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Journal was already reversed")
    if result is None:
        raise HTTPException(status_code=404, detail="Journal not found")
    response.headers["X-Prototype-Only"] = "true"
    return result


@router.get("/ledger/journals", summary="Browse posted journals and their lines")
def get_ledger_journals(
    currency: str = "ETB",
    account_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
):
    if len(currency) != 3 or not currency.isalpha() or not currency.isupper():
        raise HTTPException(status_code=422, detail="currency must be a 3-letter uppercase code")
    try:
        return {**student_store.list_ledger_journals(_org(organization_id), currency, account_id, limit, offset), "prototype_only": True}
    except LookupError:
        raise HTTPException(status_code=404, detail="Ledger account not found")


@router.get("/ledger/accounts/{account_id}/activity", summary="Read a ledger account with running balance")
def get_ledger_account_activity(
    account_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
):
    result = student_store.ledger_account_activity(_org(organization_id), account_id, limit, offset)
    if result is None:
        raise HTTPException(status_code=404, detail="Ledger account not found")
    return {**result, "prototype_only": True}


@router.get("/ledger/trial-balance", summary="Read the general-ledger trial balance")
def get_trial_balance(currency: str = "ETB", organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
    if len(currency) != 3 or not currency.isalpha() or not currency.isupper():
        raise HTTPException(status_code=422, detail="currency must be a 3-letter uppercase code")
    return {**student_store.ledger_trial_balance(_org(organization_id), currency), "prototype_only": True}
