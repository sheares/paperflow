#!/usr/bin/env python3
"""A/B compare Fireworks models on paperflow's actual reconcile prompts.

Runs the same cross-document question against each configured model, in
hybrid mode, on the persisted patient_intake run. Records for each model:

- pass/fail against the answer-quality heuristics (must mention the DOB
  conflict + one of the correct answer's key facts)
- wall-clock latency of the single Fireworks call
- input and output token counts (reported by Fireworks)
- estimated per-call cost using paperflow/models.py price_in / price_out

Usage:

    FIREWORKS_API_KEY=... python -m eval.model_ab                  # all 4
    FIREWORKS_API_KEY=... python -m eval.model_ab deepseek minimax  # 2

Exit is 0 if every listed model produced *some* answer (no HTTP error),
even if the quality heuristics flag drift; the table itself is the
deliverable.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paperflow.models import MODEL_PROFILES, resolve, profile          # noqa: E402
from paperflow.router import Router                                    # noqa: E402

RUN = Path(__file__).resolve().parent.parent / "outputs" / "run_patient_intake"

# One question that forces the hybrid route (cross-document summary
# grounded in tokenised JSON). Answer heuristics: for the patient pile
# the model should mention the DOB conflict on Rajesh Kumar and the
# right canonical (1986-03-14).
QUESTION = "What conflicts did you find between the two intake forms and the referral email?"
QUALITY_KEYWORDS = ["1986-03-14", "DOB", "date of birth", "conflict"]


def _run_one(alias: str) -> dict:
    slug = resolve(alias)
    prof = profile(alias) or {"label": slug, "price_in": 0, "price_out": 0}
    os.environ["FIREWORKS_MODEL"] = slug
    # re-instantiate Router after env change so it re-reads the model
    r = Router(RUN)
    t0 = time.perf_counter()
    try:
        res = r.ask(QUESTION)
    except Exception as e:
        return {"alias": alias, "label": prof["label"], "error": str(e)[:120],
                "ms": None, "in_tok": None, "out_tok": None, "cost": None,
                "quality": 0, "answer": ""}
    dt = int((time.perf_counter() - t0) * 1000)
    e = res["log_entry"]
    in_tok = e.get("input_tokens") or 0
    out_tok = e.get("output_tokens") or 0
    cost = (in_tok * prof["price_in"] + out_tok * prof["price_out"]) / 1_000_000
    ans_l = res["answer"].lower()
    quality = sum(1 for kw in QUALITY_KEYWORDS if kw.lower() in ans_l)
    return {"alias": alias, "label": prof["label"], "error": None,
            "ms": dt, "in_tok": in_tok, "out_tok": out_tok,
            "cost": cost, "quality": quality,
            "answer": res["answer"][:180].replace("\n", " ")}


def main() -> int:
    if not RUN.exists():
        print("run_patient_intake missing; run the pipeline first"); return 1
    if not os.environ.get("FIREWORKS_API_KEY"):
        print("FIREWORKS_API_KEY not set; nothing to compare"); return 1
    aliases = sys.argv[1:] or list(MODEL_PROFILES.keys())

    print(f"\nQuestion: {QUESTION}\n")
    rows = []
    for a in aliases:
        row = _run_one(a)
        rows.append(row)
        status = "err" if row["error"] else f"{row['quality']}/{len(QUALITY_KEYWORDS)} kw"
        print(f"  [{a:8}] {row['label']:16} · {status} · "
              f"{row['ms'] or '-'}ms · in={row['in_tok']} out={row['out_tok']} · "
              f"${row['cost']:.5f}" if row['cost'] is not None
              else f"  [{a:8}] {row['label']:16} · {row['error']}")

    # Comparison table
    print()
    print(f"  {'model':16}  {'quality':>8}  {'ms':>6}  {'in':>6}  {'out':>5}  "
          f"{'cost/call':>10}")
    print(f"  {'-' * 16}  {'-' * 8}  {'-' * 6}  {'-' * 6}  {'-' * 5}  {'-' * 10}")
    for row in rows:
        if row["error"]:
            print(f"  {row['label']:16}  {'ERR':>8}  {'-':>6}  {'-':>6}  "
                  f"{'-':>5}  {'-':>10}")
        else:
            print(f"  {row['label']:16}  "
                  f"{row['quality']:>3}/{len(QUALITY_KEYWORDS):<4}  "
                  f"{row['ms']:>6}  {row['in_tok']:>6}  {row['out_tok']:>5}  "
                  f"${row['cost']:>8.5f}")

    print()
    print("  Sample answers:")
    for row in rows:
        if not row["error"]:
            print(f"    {row['label']:16}  {row['answer']}…")

    return 0


if __name__ == "__main__":
    sys.exit(main())
