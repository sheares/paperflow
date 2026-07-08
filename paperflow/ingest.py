"""Document text loading: TXT, MD, XLSX, and text-layer PDFs (pdftotext).
Image documents (PNG/JPEG/WebP) are also enumerated so the pipeline can pass
them to the vision extractor, but they contribute empty text to the
redaction pass; the extractor's JSON output feeds the map instead."""
from __future__ import annotations

import subprocess
from pathlib import Path

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
TEXT_SUFFIXES = {".txt", ".md", ".xlsx", ".pdf"}


def load_text(path: Path) -> str:
    if path.suffix in {".txt", ".md"}:
        return path.read_text()
    if path.suffix == ".xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        lines = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    lines.append(" | ".join(cells))
        return "\n".join(lines)
    if path.suffix == ".pdf":
        out = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True, text=True, check=True)
        return out.stdout
    if path.suffix in IMAGE_SUFFIXES:
        return ""   # vision-only, no text layer to scan
    raise ValueError(f"unsupported document type: {path.suffix}")


def load_pile(pile_dir: Path) -> dict[str, str]:
    """doc filename -> extracted text, sorted for deterministic token order."""
    docs = {}
    for f in sorted(pile_dir.iterdir()):
        if f.name == "README.md" or f.is_dir():
            continue
        if f.suffix in TEXT_SUFFIXES | IMAGE_SUFFIXES:
            docs[f.name] = load_text(f)
    return docs
