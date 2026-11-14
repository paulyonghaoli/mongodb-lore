"""FastAPI app. Run:  uvicorn app.main:app --reload"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routes import ask, audit, memories, memory_review, skills

WEB = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Lore", description="Governed shared memory for analyst agents")
app.include_router(ask.router)
app.include_router(memories.router)
app.include_router(memory_review.router)
app.include_router(skills.router)
app.include_router(audit.router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")
