"""Document text loading: TXT, XLSX, and text-layer PDFs (pdftotext)."""
from __future__ import annotations

import subprocess
from pathlib import Path


def load_text(path: Path) -> str:
    if path.suffix == ".txt":
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
    raise ValueError(f"unsupported document type: {path.suffix}")


def load_pile(pile_dir: Path) -> dict[str, str]:
    """doc filename -> extracted text, sorted for deterministic token order."""
    docs = {}
    for f in sorted(pile_dir.iterdir()):
        if f.suffix in {".txt", ".xlsx", ".pdf"} and f.name != "README.md":
            docs[f.name] = load_text(f)
    return docs
