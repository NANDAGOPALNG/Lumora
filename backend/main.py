from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse

from app.api.v1.auth import router as auth_router
from app.config.settings import Settings

# Load settings and configure logging
settings = Settings.get_instance()
settings.configure_logging()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=settings.app_description,
)

app.include_router(auth_router, prefix="/api/v1")


_DEFAULT_ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never leak internal exception details (DB errors, stack traces, etc.) to clients."""
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
