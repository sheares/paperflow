"""paperflow API: serves the trust UI and (as the build progresses) the
pipeline + chat endpoints. Route (b): the verified mockup is the front end.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="paperflow")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index():
    return FileResponse(ROOT / "ui" / "index.html")
