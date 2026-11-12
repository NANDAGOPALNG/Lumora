import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.connectors import router as connectors_router
from app.api.v1.document import router as documents_router
from app.api.v1.search import router as search_router
from app.api.v1.workspace import router as workspaces_router
from app.config.settings import Settings
from app.database.session import dispose_engine
from app.storage.factory import BACKEND_LOCAL, configured_backend, validate_storage_configuration

# Load settings and configure logging
settings = Settings.get_instance()
settings.configure_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Fail fast, with a clear message that names the missing variables (never
    # their values), if DOCUMENT_STORAGE_BACKEND=r2 is selected but R2 is not
    # fully configured. Makes no network call.
    validate_storage_configuration()
    if settings.is_production() and configured_backend(settings) == BACKEND_LOCAL:
        logger.warning(
            "DOCUMENT_STORAGE_BACKEND=local in production: uploaded files are "
            "kept on this server's disk, which is lost on redeploy/restart on "
            "ephemeral hosts (e.g. Render Free). Set DOCUMENT_STORAGE_BACKEND=r2."
        )
    yield
    # Release pooled database connections on shutdown.
    await dispose_engine()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=settings.app_description,
    lifespan=lifespan,
)

# Authentication uses a Bearer token in the Authorization header (no
# cookies), so credentials are not allowed cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(workspaces_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(search_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(connectors_router, prefix="/api/v1")


_DEFAULT_ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    413: "FILE_TOO_LARGE",
    415: "UNSUPPORTED_FILE_TYPE",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
    500: "INTERNAL_SERVER_ERROR",
}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Render HTTPExceptions using the API specification's error envelope."""
    if isinstance(exc.detail, dict) and "code" in exc.detail and "message" in exc.detail:
        error = exc.detail
    else:
        error = {
            "code": _DEFAULT_ERROR_CODES.get(exc.status_code, "ERROR"),
            "message": str(exc.detail),
        }

    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": error},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Render FastAPI's request validation errors using the same error envelope."""
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": {"code": "VALIDATION_ERROR", "message": "Invalid request"},
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never leak internal exception details (DB errors, stack traces, etc.) to clients.

    The full exception is logged server-side so failures stay diagnosable.
    """
    logger.error("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {"code": "INTERNAL_SERVER_ERROR", "message": "An unexpected error occurred"},
        },
    )


@app.get("/")
def root():
    return {"message": "Welcome to Lumora API"}

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "environment": settings.environment.value,
        "app_name": settings.app_name
    }
