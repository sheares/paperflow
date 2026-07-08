#!/usr/bin/env python3
"""The eval scorer: run_output.json vs ground_truth.json, per pile.

Four scored tasks (the "realised and functional" evidence):
  conflict detection  - planted conflicts flagged as conflicts
  conflict resolution - resolved value equals the planted `correct`
  gap flagging        - planted gaps flagged missing
  alias resolution    - planted alias groups merged, not flagged
  redaction recall    - planted sensitive spans absent from redacted text

Precision is reported where false positives are measurable (conflicts,
gaps). Redaction is recall-only by design. Unplanted-but-true extra alias
merges are listed, not penalised.

Usage: python eval/scorer.py [--pile synthetic/kyc_onboarding] [--json]
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYN = ROOT / "synthetic"
OUT = ROOT / "outputs"


ABBREV = {"sg": "singapore", "blk": "block", "rd": "road", "ave": "avenue",
          "st": "street"}


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def _eq(a: str, b: str) -> bool:
    """Equality up to whitespace and common SG address abbreviations."""
    fold = lambda s: " ".join(ABBREV.get(w, w) for w in squash(s).split())  # noqa: E731
    return fold(a) == fold(b)


def score_pile(pile: str) -> dict:
    gt = json.loads((SYN / pile / "ground_truth.json").read_text())
    run = json.loads((OUT / f"run_{pile}" / "run_output.json").read_text())
    redacted = json.loads((OUT / f"run_{pile}" / "redacted_docs.json").read_text())

    # entity lookup: gt names -> record (display or alias group membership)
    def find_record(entity_name: str) -> dict | None:
        for rec in run["records"]:
            if squash(rec["entity_display"]) == squash(entity_name):
                return rec
        for group in run["alias_groups"]:
            if any(squash(g) == squash(entity_name) for g in group):
                for rec in run["records"]:
                    if squash(rec["entity_display"]) in {squash(g) for g in group}:
                        return rec
        # the gt entity may be a CONTACT of the record's entity (partner
        # piles key on the organisation; conflicts name the person)
        for rec in run["records"]:
            for f in rec["fields"].values():
                if f.get("value") and squash(str(f["value"])) == squash(entity_name):
                    return rec
        return None

    def norm_key(field: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", field.lower()).strip("_")

    r: dict = {"pile": pile}

    # ---- conflicts: detection + resolution ----
    det_tp = res_tp = 0
    planted = gt["planted_conflicts"]
    conflict_statuses = {"conflict", "resolved_conflict", "escalated"}
    for c in planted:
        rec = find_record(c["entity"])
        f = (rec or {}).get("fields", {}).get(norm_key(c["field"]))
        detected = bool(f) and f["status"] in conflict_statuses
        det_tp += detected
        if detected and c.get("correct") is not None:
            res_tp += _eq(str(f.get("value")), c["correct"])
        elif detected and c.get("correct") is None:
            res_tp += f["status"] == "escalated"   # ambiguity must escalate
    # extra reported conflicts are listed, not penalised: the ground truth
    # enumerates planted items, it is not an exhaustive truth (verified
    # example: an unplanted-but-real rsvp divergence in the partner pile)
    planted_fields = {(norm_key(c["field"])) for c in planted}
    extras = [f"{rec['entity_display']} · {k}"
              for rec in run["records"] for k, f in rec["fields"].items()
              if f["status"] in conflict_statuses and k not in planted_fields]
    r["conflict_detection"] = {"tp": det_tp, "support": len(planted),
                               "recall": det_tp / len(planted) if planted else 1,
                               "unscored_extras": extras}
    r["conflict_resolution"] = {"tp": res_tp, "support": len(planted),
                                "recall": res_tp / len(planted) if planted else 1}

    # ---- gaps ----
    gap_tp = 0
    for g in gt["planted_gaps"]:
        rec = find_record(g["entity"])
        f = (rec or {}).get("fields", {}).get(norm_key(g["field"]))
        gap_tp += bool(f) and f["status"] == "missing"
    planted_gap_fields = {norm_key(g["field"]) for g in gt["planted_gaps"]}
    gap_extras = [f"{rec['entity_display']} · {k}"
                  for rec in run["records"] for k, f in rec["fields"].items()
                  if f["status"] == "missing" and k not in planted_gap_fields]
    n_gaps = len(gt["planted_gaps"])
    r["gap_flagging"] = {"tp": gap_tp, "support": n_gaps,
                         "recall": gap_tp / n_gaps if n_gaps else 1,
                         "unscored_extras": gap_extras}

    # ---- aliases ----
    alias_tp, extras = 0, []
    gt_groups = gt["alias_variations"]
    planted_names = {squash(n) for g in gt_groups
                     for n in [g["canonical"], *g["aliases"]]}
    for g in gt_groups:
        want = {squash(n) for n in [g["canonical"], *g["aliases"]]}
        alias_tp += any(want <= {squash(x) for x in group}
                        for group in run["alias_groups"])
    for group in run["alias_groups"]:
        if not ({squash(x) for x in group} & planted_names):
            extras.append(group)
    r["alias_resolution"] = {"tp": alias_tp, "support": len(gt_groups),
                             "recall": alias_tp / len(gt_groups) if gt_groups else 1,
                             "unscored_extra_merges": extras}

    # ---- redaction recall ----
    all_red = squash(" ".join(redacted.values()))
    spans = gt["sensitive_spans"]
    leaked = [s["value"] for s in spans if squash(s["value"]) in all_red]
    r["redaction_recall"] = {"tp": len(spans) - len(leaked),
                             "support": len(spans),
                             "recall": (len(spans) - len(leaked)) / len(spans),
                             "leaked": leaked}
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pile", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    piles = [args.pile.name] if args.pile else \
        [p.name for p in sorted(SYN.iterdir())
         if p.is_dir() and (p / "ground_truth.json").exists()]

    results = [score_pile(p) for p in piles]
    if args.json:
        print(json.dumps(results, indent=1))
        return 0

    tasks = ["conflict_detection", "conflict_resolution", "gap_flagging",
             "alias_resolution", "redaction_recall"]
    print(f"{'task':<22}" + "".join(f"{r['pile'][:15]:>17}" for r in results)
          + f"{'OVERALL':>16}")
    overall_fail = 0
    for t in tasks:
        cells, tp, sup = [], 0, 0
        for r in results:
            m = r[t]
            tp += m["tp"]; sup += m["support"]
            cells.append(f"{m['tp']}/{m['support']}".rjust(17))
        overall = f"{tp}/{sup} ({tp / sup:.0%})" if sup else "n/a"
        print(f"{t:<22}" + "".join(cells) + overall.rjust(16))
        overall_fail += sup - tp
    for r in results:
        if r["redaction_recall"]["leaked"]:
            print(f"  LEAKED in {r['pile']}: {r['redaction_recall']['leaked']}")
        for t in ("conflict_detection", "gap_flagging", "alias_resolution"):
            key = "unscored_extras" if t != "alias_resolution" else "unscored_extra_merges"
            if r[t].get(key):
                print(f"  unscored extras ({t}) in {r['pile']}: {r[t][key]}")
    print("\nSCORER:", "ALL TASKS PERFECT" if overall_fail == 0
          else f"{overall_fail} misses (see above)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
