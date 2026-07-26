from fastapi import FastAPI

app = FastAPI(
    title="Lumora API",
    version="1.0.0",
    description="Enterprise AI Knowledge Platform"
)

@app.get("/")
def root():
    return {"message": "Welcome to Lumora API"}

@app.get("/health")
def health():
    return {
        "status": "healthy"
    }