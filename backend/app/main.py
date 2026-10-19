from contextlib import asynccontextmanager
import re
from uuid import uuid4
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.routers.health import router as health_router
from app.routers.students import router as students_router
from app.routers.guardians import router as guardians_router, directory_router as guardian_directory_router
from app.routers.attendance import router as attendance_router
from app.routers.academics import router as academics_router
from app.routers.classrooms import router as classrooms_router
from app.routers.finance import router as finance_router
from app.routers.auth import router as auth_router
from app.routers.sync import router as sync_router
from app.services import auth_service
from fastapi import Request
from fastapi.responses import JSONResponse
from app.services.student_store import initialize as initialize_dev_store

settings = get_settings()


def ensure_non_production_runtime(environment: str) -> None:
    """Fail closed: this starter API must not be launched as a production service."""
    if environment.strip().lower() in {"prod", "production"}:
        raise RuntimeError(
            "This School Management System starter is not production-ready. "
            "Production startup is blocked until authentication/authorization, "
            "approved production persistence, migrations, and operational controls are implemented."
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_non_production_runtime(settings.environment)
    if settings.auth_required:
        auth_service._secret()
    # Disposable local prototype storage only; replace after final schema approval.
    initialize_dev_store()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "School management API prototype. Student CRUD uses disposable local SQLite storage "
        "for development only. Prototype authentication is opt-in; production authorization, "
        "approved persistence, guardian records, accounting, and offline sync are not production-ready. The sync endpoint is validation-only and rejects domain mutations. Do not use real personal data."
    ),
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    lifespan=lifespan,
)

@app.middleware("http")
async def enforce_bearer_auth_when_enabled(request: Request, call_next):
    """Optional enforcement switch for integration testing and staged deployments."""
    if settings.auth_required and request.url.path.startswith("/api/v1/"):
        path = request.url.path
        public_paths = {"/api/v1/auth/login", "/api/v1/auth/bootstrap-admin", "/api/v1/openapi.json", "/api/v1/docs", "/api/v1/redoc"}
        if path not in public_paths and not path.startswith("/api/v1/docs/"):
            authorization = request.headers.get("Authorization", "")
            if not authorization.startswith("Bearer "):
                return JSONResponse(status_code=401, content={"detail": "Bearer access token required"}, headers={"WWW-Authenticate": "Bearer"})
            try:
                claims = auth_service.verify_access_token(authorization[7:].strip())
                user = auth_service.user_by_id(claims["sub"], claims["org"])
                if not user or not user["is_active"] or user["role"] != claims["role"]:
                    raise ValueError("inactive or changed user")
                supplied_org = request.headers.get("X-Organization-ID")
                if supplied_org and supplied_org.strip() != claims["org"]:
                    return JSONResponse(status_code=403, content={"detail": "Organization header does not match authenticated user"})
                # In authenticated mode, make the signed token's tenant authoritative.
                # Domain routers consume X-Organization-ID; never require callers to
                # repeat a tenant claim that is already bound to their verified token.
                if not supplied_org:
                    raw_headers = list(request.scope.get("headers", []))
                    raw_headers.append((b"x-organization-id", claims["org"].encode("utf-8")))
                    request.scope["headers"] = raw_headers
                if not auth_service.role_allows(claims["role"], request.method, path):
                    return JSONResponse(status_code=403, content={"detail": "Role is not permitted to perform this action"})
                request.state.auth_user = {**claims, "email": user["email"]}
            except (ValueError, RuntimeError):
                return JSONResponse(status_code=401, content={"detail": "Invalid or expired access token"}, headers={"WWW-Authenticate": "Bearer"})
    return await call_next(request)


@app.middleware("http")
async def security_response_headers(request: Request, call_next):
    """Set conservative browser protections; this does not replace production hardening."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/api/v1/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.middleware("http")
async def request_correlation_id(request, call_next):
    """Attach a safe correlation ID to every response for support/debugging."""
    supplied = request.headers.get("X-Request-ID", "")
    request_id = supplied if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied) else str(uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key", "X-Organization-ID", "X-Bootstrap-Token"],
)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(students_router)
app.include_router(guardians_router)
app.include_router(guardian_directory_router)
app.include_router(attendance_router)
app.include_router(academics_router)
app.include_router(classrooms_router)
app.include_router(finance_router)
app.include_router(sync_router)


@app.get("/", tags=["operations"], summary="API information")
def root() -> dict[str, str]:
    return {
        "service": "school-management-api",
        "version": settings.app_version,
        "environment": settings.environment,
        "docs": "/api/v1/docs",
        "status": "prototype",
    }
