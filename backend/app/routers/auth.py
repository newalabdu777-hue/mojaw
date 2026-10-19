"""Authentication API for the development prototype; keep production startup blocked."""
import os
import re
import sqlite3
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from app.services import auth_service

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: str = Field(min_length=1, max_length=64)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class BootstrapAdminRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: str = Field(min_length=1, max_length=64)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    role: str = Field(min_length=1, max_length=40)


def _bearer(authorization: Annotated[str | None, Header()] = None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer access token required", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = auth_service.verify_access_token(authorization[7:].strip())
    except (ValueError, RuntimeError):
        raise HTTPException(status_code=401, detail="Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"})
    user = auth_service.user_by_id(claims["sub"], claims["org"])
    if not user or not user["is_active"] or user["role"] != claims["role"]:
        raise HTTPException(status_code=401, detail="User is inactive or token is no longer valid", headers={"WWW-Authenticate": "Bearer"})
    return {**claims, "email": user["email"]}


def require_admin(claims: dict = Depends(_bearer)) -> dict:
    if claims["role"] != "organization_admin":
        raise HTTPException(status_code=403, detail="Organization administrator role required")
    return claims


@router.post("/bootstrap-admin", status_code=201, summary="Create the first organization administrator (bootstrap only)")
def bootstrap_admin(payload: BootstrapAdminRequest, x_bootstrap_token: Annotated[str | None, Header()] = None):
    expected = os.environ.get("SCHOOL_BOOTSTRAP_TOKEN", "")
    if len(expected) < 32 or not x_bootstrap_token or not __import__("hmac").compare_digest(expected, x_bootstrap_token):
        raise HTTPException(status_code=403, detail="Bootstrap is disabled or token is invalid")
    try:
        user = auth_service.create_first_admin(payload.organization_id, payload.email, payload.password)
    except (sqlite3.IntegrityError, RuntimeError):
        raise HTTPException(status_code=409, detail="This organization already has a user; bootstrap is closed")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"user": user, "message": "Administrator created. Remove SCHOOL_BOOTSTRAP_TOKEN after bootstrap."}


@router.post("/login", summary="Exchange credentials for a short-lived access token")
def login(payload: LoginRequest):
    if not re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", payload.email.strip()):
        raise HTTPException(status_code=401, detail="Invalid organization, email, or password")
    organization_id, email = payload.organization_id.strip(), payload.email.strip().lower()
    blocked_for = auth_service.login_block_seconds(organization_id, email)
    if blocked_for:
        raise HTTPException(status_code=429, detail="Too many failed login attempts. Try again later.", headers={"Retry-After": str(blocked_for)})
    try:
        user = auth_service.authenticate(organization_id, email, payload.password)
        token = auth_service.create_access_token(user) if user else None
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Authentication is not configured; set a strong SCHOOL_AUTH_SECRET")
    if not user or not token:
        blocked_for = auth_service.record_login_failure(organization_id, email)
        if blocked_for:
            raise HTTPException(status_code=429, detail="Too many failed login attempts. Try again later.", headers={"Retry-After": str(blocked_for)})
        raise HTTPException(status_code=401, detail="Invalid organization, email, or password", headers={"WWW-Authenticate": "Bearer"})
    auth_service.clear_login_failures(organization_id, email)
    return {"access_token": token, "token_type": "bearer", "expires_in": auth_service.TOKEN_TTL_SECONDS, "user": user}


@router.get("/me", summary="Get the current authenticated user")
def me(claims: dict = Depends(_bearer)):
    return {"user_id": claims["sub"], "organization_id": claims["org"], "email": claims["email"], "role": claims["role"]}


@router.get("/users", summary="List users in the current organization (admin only)")
def users(limit: int = 100, offset: int = 0, claims: dict = Depends(require_admin)):
    if limit < 1 or limit > 200 or offset < 0:
        raise HTTPException(status_code=422, detail="limit must be 1..200 and offset must be non-negative")
    return auth_service.list_users(claims["org"], limit, offset)


@router.post("/users", status_code=201, summary="Create a user in the current organization (admin only)")
def create_user(payload: CreateUserRequest, claims: dict = Depends(require_admin)):
    try:
        return auth_service.create_user(claims["org"], payload.email, payload.password, payload.role)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="A user with this email already exists in the organization")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
