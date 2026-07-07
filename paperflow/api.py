"""paperflow API: serves the trust UI, pile views shaped for it, and the
chat router. Route (b): the verified mockup is the front end.

If FIREWORKS_API_KEY is absent, everything runs full-local (zero egress);
the UI's receipts reflect whichever route actually executed.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .pipeline import run_pile
from .router import Router
from .uiview import build_pile_view

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs"
PILES = {
    "kyc_onboarding": "kyc",
    "patient_intake": "patient",
    "partner_collation": "partner",
}

app = FastAPI(title="paperflow")
_routers: dict[str, Router] = {}


def _schema(pile: str) -> Path:
    return ROOT / "paperflow" / "schemas" / f"{PILES[pile]}.yaml"


def _ensure_run(pile: str, full_local: bool | None = None) -> Path:
    if pile not in PILES:
        raise HTTPException(404, f"unknown pile {pile}")
    run_dir = OUT / f"run_{pile}"
    if not (run_dir / "run_output.json").exists():
        if full_local is None:
            full_local = "FIREWORKS_API_KEY" not in os.environ
        cached = OUT / f"extraction_{pile}.json"
        run_pile(ROOT / "synthetic" / pile, _schema(pile),
                 cached if cached.exists() else None, full_local, OUT)
        _routers.pop(pile, None)
    return run_dir


class AskBody(BaseModel):
    pile: str
    question: str
    full_local: bool = False


class RunBody(BaseModel):
    pile: str
    full_local: bool | None = None


@app.get("/health")
def health():
    return {"status": "ok", "remote_available": "FIREWORKS_API_KEY" in os.environ}


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    # tiny inline PNG (no external asset needed)
    from fastapi.responses import Response
    return Response(status_code=204)


@app.get("/")
def index():
    return FileResponse(ROOT / "ui" / "index.html")


@app.get("/api/piles")
def piles():
    return {"piles": list(PILES)}


@app.get("/api/doc/{pile}/{filename}")
def get_doc(pile: str, filename: str):
    if pile not in PILES or "/" in filename or ".." in filename:
        raise HTTPException(404, "not found")
    path = ROOT / "synthetic" / pile / filename
    if not path.exists():
        raise HTTPException(404, "not found")
    mime = {"pdf": "application/pdf", "txt": "text/plain",
            "md": "text/markdown",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            }.get(path.suffix.lstrip("."), "application/octet-stream")
    from fastapi.responses import FileResponse
    return FileResponse(path, media_type=mime)


@app.get("/api/pile/{pile}")
def pile_view(pile: str):
    run_dir = _ensure_run(pile)
    extraction = OUT / f"extraction_{pile}.json"
    if not extraction.exists():
        raise HTTPException(409, "no extraction artefact; run a GPU session "
                                 "or POST /api/run first")
    return build_pile_view(run_dir, extraction, _schema(pile))


@app.post("/api/run")
def run(body: RunBody):
    run_dir = _ensure_run(body.pile, body.full_local)
    return {"ok": True, "run_dir": str(run_dir)}


@app.post("/api/ask")
def ask(body: AskBody):
    run_dir = _ensure_run(body.pile)
    if body.pile not in _routers:
        _routers[body.pile] = Router(run_dir)
    full_local = body.full_local or "FIREWORKS_API_KEY" not in os.environ
    return _routers[body.pile].ask(body.question, full_local=full_local)
