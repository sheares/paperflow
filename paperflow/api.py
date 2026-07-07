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


@app.get("/api/xlsx_preview/{pile}/{filename}")
def xlsx_preview(pile: str, filename: str, n: int = 5):
    if pile not in PILES or "/" in filename or ".." in filename:
        raise HTTPException(404, "not found")
    path = ROOT / "synthetic" / pile / filename
    if not path.exists() or path.suffix != ".xlsx":
        raise HTTPException(404, "not found")
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    sheets = []
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append(["" if c is None else str(c) for c in row])
            if len(rows) >= n:
                break
        sheets.append({"name": ws.title, "rows": rows,
                       "total_rows": ws.max_row, "total_cols": ws.max_column})
    return {"sheets": sheets, "showing": n}


class RedactBody(BaseModel):
    text: str


@app.post("/api/redact")
def redact(body: RedactBody):
    """Paste-and-redact sandbox. No pile, no reconciliation: just the
    privacy round-trip on the submitted text, so anyone can watch their
    own words get tokenised. Text stays in memory; no logging, no
    persistence."""
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "empty text")
    if len(text) > 20_000:
        raise HTTPException(413, "text too large (max 20k characters)")
    from paperflow.privacy.redactor import PrivacyRoundTrip
    result = PrivacyRoundTrip().process_pile({"pasted.txt": text})
    emap = result.entity_map
    entities = []
    for tok, canonical in emap.token_to_value.items():
        forms = sorted({emap._display[k] for k, t in emap._lookup.items()
                        if t == tok})
        family = tok.strip("[]").rsplit("_", 1)[0]
        entities.append({"token": tok, "family": family, "forms": forms,
                         "canonical": canonical})
    return {
        "original": text,
        "redacted": result.redacted["pasted.txt"],
        "rehydrated": emap.rehydrate(result.redacted["pasted.txt"]),
        "entities": entities,
        "counts": {"tokens": len(emap.token_to_value),
                   "surface_forms": len(emap._lookup)},
    }


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
