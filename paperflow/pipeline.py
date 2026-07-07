"""End-to-end pipeline: ingest -> redact/map -> (extraction) -> reconcile ->
audit -> emit run_output.json.

The run_output contract (consumed by eval/scorer.py and the UI):
  records, alias_groups, redaction_log, router_log
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import yaml

from .extractor import extract_pile
from .ingest import load_pile
from .privacy.redactor import PrivacyRoundTrip
from .reconciler import Reconciler, _family_for

SYNONYMS = {
    "nric": ["nric_fin", "national_id"],
    "national_id_nric": ["national_id", "nric_fin"],
    "dob": ["date_of_birth"],
    "address": ["residential_address"],
    "company": ["organisation"],
    "organization": ["organisation"],
    "name": [],   # too ambiguous; resolved via entity_field below
}
NOISE_LABELS = {"doc_id", "doc", "document_id", "page"}


def _norm_label(label: str, schema_keys: list[str], entity_field: str) -> str | None:
    key = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    if key in NOISE_LABELS:
        return None
    if key in schema_keys:
        return key
    for target in SYNONYMS.get(key, []):
        if target in schema_keys:
            return target
    if key == "name":
        return entity_field
    return key  # keep extras; reconciliation only runs on schema keys


def run_pile(pile_dir: Path, schema_path: Path, cached_extraction: Path | None,
             full_local: bool, out_root: Path) -> Path:
    spec = yaml.safe_load(schema_path.read_text())
    schema_keys = [f["key"] for f in spec["required_fields"]]
    entity_field = spec["entity_field"]

    # 1-2. ingest + privacy round-trip over raw text (builds the master map)
    docs_text = load_pile(pile_dir)
    rt = PrivacyRoundTrip()
    red = rt.process_pile(docs_text)
    emap = red.entity_map

    # extraction (cached from a GPU session, or live against VLLM_URL)
    if cached_extraction and cached_extraction.exists():
        extraction = json.loads(cached_extraction.read_text())
    else:
        extraction = asyncio.run(extract_pile(pile_dir, schema_path)).to_dict()

    # register extracted values into the map (extractor catches what raw-text
    # analysis may phrase differently), then group fields by entity
    records_raw: dict[str, dict[str, list]] = {}
    for doc in extraction["docs"]:
        fields = {}
        for f in doc["fields"]:
            key = _norm_label(f["label"], schema_keys, entity_field)
            value = f["value"].strip()
            # extractor null artefacts must not fill genuine gaps
            # ("none known" for allergies is meaningful and stays)
            if value.lower() in {"none", "null", "n/a", "-", ""}:
                continue
            if key:
                fields.setdefault(key, value)
        for key, value in fields.items():
            if key in schema_keys:
                emap.add(value, _family_for(key))

        ent_value = fields.get(entity_field)
        etoken = emap.token_of(ent_value) if ent_value else None
        if etoken is None:
            # fallback: first person/org token present in the doc's redacted text
            rtext = red.redacted.get(doc["doc"], "")
            m = re.search(r"\[(?:PERSON|ORG)_\d+\]", rtext)
            etoken = m.group(0) if m else "[UNASSIGNED]"
        bucket = records_raw.setdefault(etoken, {})
        for key, value in fields.items():
            if key in schema_keys:
                bucket.setdefault(key, [])
                if not any(v == value for _, v in bucket[key]):
                    bucket[key].append((doc["doc"], value))
                else:
                    bucket[key] = [(d, v) if v != value else (d + "," + doc["doc"], v)
                                   for d, v in bucket[key]]

    # 3. reconcile
    rec = Reconciler(full_local=full_local)
    records, conflicts = rec.detect_conflicts(records_raw, schema_keys, emap)
    decisions = rec.decide(pile_dir.name, conflicts)
    for d in decisions:
        slot = records[d.entity_token][d.field_key]
        slot["decision"] = d.to_artifact()
        if d.chosen_token and not d.escalate:
            slot["value"] = emap.rehydrate(d.chosen_token)
            slot["status"] = "resolved_conflict"
            slot["confidence"] = d.confidence
        else:
            slot["status"] = "escalated"

    # 4. audit: required fields missing everywhere for an entity = gap
    for etoken, fields_ in records.items():
        for key in schema_keys:
            if key not in fields_:
                fields_[key] = {"value": None, "sources": [], "status": "missing",
                                "variants": []}

    # 5. emit
    alias_groups = {}
    for k, token in emap._lookup.items():
        fam = token.strip("[]").rsplit("_", 1)[0]
        if fam in {"PERSON", "ORG"}:
            alias_groups.setdefault(token, []).append(emap._display[k])
    out = {
        "pile": pile_dir.name,
        "records": [{"entity_id": t, "entity_display": emap.rehydrate(t),
                     "fields": f} for t, f in records.items()],
        "alias_groups": [v for v in alias_groups.values() if len(v) > 1],
        "redaction_log": [{"token": t, "surface_forms":
                           [d for k, d in emap._display.items()
                            if emap._lookup[k] == t]}
                          for t in emap.token_to_value],
        "router_log": rec.router_log,
    }
    run_dir = out_root / f"run_{pile_dir.name}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_output.json").write_text(json.dumps(out, indent=1))
    (run_dir / "entity_map.json").write_text(emap.to_json())
    (run_dir / "redacted_docs.json").write_text(json.dumps(red.redacted, indent=1))
    return run_dir / "run_output.json"


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pile", required=True, type=Path)
    ap.add_argument("--schema", required=True, type=Path)
    ap.add_argument("--cached-extraction", type=Path)
    ap.add_argument("--full-local", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("outputs"))
    args = ap.parse_args()
    out = run_pile(args.pile, args.schema, args.cached_extraction,
                   args.full_local, args.out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
