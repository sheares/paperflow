"""Extractor: Gemma 4 31B IT (vision) via a vLLM OpenAI-compatible endpoint.

Concurrent per-document extraction: a pile of N docs takes roughly the time
of the slowest doc, not the sum. Output feeds the run_output.json contract:
every field carries provenance (doc), value, and model confidence.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml

from .ingest import load_text

VLLM_URL = os.environ.get("VLLM_URL", "http://localhost:8000/v1")
VLLM_MODEL = os.environ.get("VLLM_MODEL", "google/gemma-4-31b-it")
MAX_CONCURRENCY = 4

PROMPT = (
    "You are a document extraction engine. Extract every field you can find "
    "from this document. Target schema (extract these when present, plus any "
    "other identifying fields): {schema}. Return STRICT JSON only: "
    '{{"fields": [{{"label": "...", "value": "...", "confidence": 0.0}}]}}. '
    "Transcribe values exactly as written, including any apparent errors. "
    "Confidence reflects how legible and unambiguous the value is (0 to 1)."
)


@dataclass
class DocExtraction:
    doc: str
    kind: str                 # vision | text
    fields: list[dict]
    latency_s: float
    error: str | None = None
    raw: str = ""


@dataclass
class PileExtraction:
    pile: str
    docs: list[DocExtraction] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "pile": self.pile,
            "docs": [{
                "doc": d.doc, "kind": d.kind, "latency_s": round(d.latency_s, 2),
                "fields": d.fields, "error": d.error,
            } for d in self.docs],
        }


def load_schema(path: Path) -> str:
    spec = yaml.safe_load(path.read_text())
    return ", ".join(f["key"] for f in spec["required_fields"])


def _pdf_content(pdf: Path) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-png", "-r", "150", str(pdf), f"{tmp}/p"],
                       check=True)
        parts = []
        for png in sorted(Path(tmp).glob("p*.png")):
            b64 = base64.b64encode(png.read_bytes()).decode()
            parts.append({"type": "image_url",
                          "image_url": {"url": f"data:image/png;base64,{b64}"}})
        return parts


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _doc_content(path: Path) -> tuple[list[dict], str]:
    if path.suffix == ".pdf":
        return _pdf_content(path), "vision"
    if path.suffix in IMAGE_SUFFIXES:
        mime = "jpeg" if path.suffix in {".jpg", ".jpeg"} else path.suffix[1:]
        b64 = base64.b64encode(path.read_bytes()).decode()
        return [{"type": "image_url",
                 "image_url": {"url": f"data:image/{mime};base64,{b64}"}}], "vision"
    text = load_text(path)
    return [{"type": "text", "text": f"DOCUMENT ({path.name}):\n{text}"}], "text"


def _parse_fields(content: str) -> list[dict]:
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.M)
    data = json.loads(body)
    out = []
    for f in data.get("fields", []):
        if isinstance(f, dict) and f.get("label") is not None:
            out.append({"label": str(f.get("label", "")),
                        "value": str(f.get("value", "")),
                        "confidence": float(f.get("confidence", 0.0))})
    return out


async def _extract_doc(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                       path: Path, schema: str) -> DocExtraction:
    content, kind = _doc_content(path)
    body = {
        "model": VLLM_MODEL,
        "messages": [{"role": "user", "content":
                      [{"type": "text", "text": PROMPT.format(schema=schema)}] + content}],
        "max_tokens": 2000,
        "temperature": 0,
    }
    async with sem:
        t0 = time.time()
        try:
            r = await client.post(f"{VLLM_URL}/chat/completions", json=body)
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"]
            return DocExtraction(doc=path.name, kind=kind,
                                 fields=_parse_fields(raw),
                                 latency_s=time.time() - t0, raw=raw)
        except Exception as e:  # noqa: BLE001 - a failed doc must not sink the pile
            return DocExtraction(doc=path.name, kind=kind, fields=[],
                                 latency_s=time.time() - t0, error=str(e))


async def extract_pile(pile_dir: Path, schema_path: Path) -> PileExtraction:
    schema = load_schema(schema_path)
    docs = [f for f in sorted(pile_dir.iterdir())
            if f.suffix in {".pdf", ".txt", ".md", ".xlsx"} | IMAGE_SUFFIXES
            and f.name != "README.md"]
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    async with httpx.AsyncClient(timeout=180) as client:
        results = await asyncio.gather(
            *(_extract_doc(client, sem, d, schema) for d in docs))
    return PileExtraction(pile=pile_dir.name, docs=list(results))


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pile", required=True, type=Path)
    ap.add_argument("--schema", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=Path("outputs"))
    args = ap.parse_args()

    t0 = time.time()
    result = asyncio.run(extract_pile(args.pile, args.schema))
    wall = time.time() - t0

    args.out.mkdir(parents=True, exist_ok=True)
    out_file = args.out / f"extraction_{result.pile}.json"
    out_file.write_text(json.dumps(result.to_dict(), indent=1))

    for d in result.docs:
        status = f"{len(d.fields)} fields" if not d.error else f"ERROR {d.error[:60]}"
        print(f"  {d.doc} ({d.kind}): {d.latency_s:.1f}s · {status}")
    slowest = max(d.latency_s for d in result.docs)
    print(f"pile wall time {wall:.1f}s (slowest doc {slowest:.1f}s, "
          f"sequential would be {sum(d.latency_s for d in result.docs):.1f}s)")
    print(f"wrote {out_file}")


if __name__ == "__main__":
    main()
