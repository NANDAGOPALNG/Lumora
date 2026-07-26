from fastapi import FastAPI
from app.config.settings import Settings

# Load settings and configure logging
settings = Settings.get_instance()
settings.configure_logging()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=settings.app_description,
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