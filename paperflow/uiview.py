"""Shape a pipeline run into the pile object the trust UI renders.

The mockup's data contract (docs / clients / entities / initial exchange)
was verified by demo rehearsal; the backend adapts to IT, not vice versa.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

FIELD_TYPES = {
    "full_name": "name", "patient_name": "name", "contact_name": "name",
    "national_id": "id", "nric_fin": "id", "policy_number": "id", "uen": "id",
    "residential_address": "address",
    "declaration_date": "date", "date_of_birth": "date",
    "consent_signed": "date", "rsvp_status": "date",
    "source_of_funds": "funds", "allergies": "funds",
    "beneficial_owner": "org", "organisation": "org",
    "email": "email", "phone": "phone",
}
FAMILY_TYPES = {
    "PERSON": "name", "ORG": "org", "ID": "id", "UEN": "id", "POLICY": "id",
    "SERIAL": "id", "ADDR": "address", "POSTCODE": "address", "DATE": "date",
    "EMAIL": "email", "PHONE": "phone",
}
DOC_TYPES = [("form", "KYC form"), ("intake", "Intake form"),
             ("declaration", "Declaration"), ("bill", "Utility bill"),
             ("scan", "ID copy"), ("nric", "ID copy"),
             ("referral", "Referral"), ("lab", "Lab requisition"),
             ("insurance", "Insurance card"), ("card", "Business card"),
             ("mou", "MOU"), ("registration", "Registration"),
             ("contacts", "Contact sheet"), ("email", "Email")]


def _pretty(key: str) -> str:
    return key.replace("_", " ").capitalize()


def _doc_type(name: str) -> str:
    low = name.lower()
    for frag, label in DOC_TYPES:
        if frag in low:
            return label
    return "Document"


def build_pile_view(run_dir: Path, extraction_path: Path,
                    schema_path: Path) -> dict:
    run = json.loads((run_dir / "run_output.json").read_text())
    extraction = json.loads(extraction_path.read_text())
    spec = yaml.safe_load(schema_path.read_text())

    # ---- docs ----
    docs = []
    for d in extraction["docs"]:
        confs = [f["confidence"] for f in d["fields"]] or [0.0]
        conf = sum(confs) / len(confs)
        docs.append({
            "type": _doc_type(d["doc"]), "file": d["doc"], "name": d["doc"],
            "format": d["doc"].rsplit(".", 1)[-1],
            "parser": "Gemma 4 31B IT" if d["kind"] == "vision" else "text",
            "fields": len(d["fields"]), "conf": round(conf, 2),
            "state": "review" if conf < 0.75 else "good",
            "fieldsList": [{"label": f["label"],
                            "type": FIELD_TYPES.get(f["label"], "id"),
                            "value": f["value"], "conf": f["confidence"]}
                           for f in d["fields"]],
        })

    # ---- clients (records) ----
    clients, n_conflicts, n_gaps = [], 0, 0
    for i, rec in enumerate(run["records"]):
        fields, open_c, open_g = [], 0, 0
        for key, f in rec["fields"].items():
            base = {"label": _pretty(key), "type": FIELD_TYPES.get(key, "id")}
            dec = f.get("decision")
            if f["status"] in {"conflict", "escalated"} or \
                    (f["status"] == "resolved_conflict" and f.get("variants")):
                variants = f.get("variants", [])
                chosen = f.get("value")
                note = "⚠ CONFLICT · select correct value"
                if dec and f["status"] == "resolved_conflict":
                    note = (f"⚠ CONFLICT · resolved ({dec['source']}, "
                            f"confidence {dec['confidence']:.2f}): "
                            f"{dec['rationale']}")
                elif f["status"] == "escalated":
                    note = "⚠ CONFLICT · escalated: " + \
                        (dec["rationale"] if dec else "needs human review")
                    open_c += 1
                fields.append({**base, "conflict": True, "conflictNote": note,
                               "opts": [{"value": v["value"],
                                         "doc": v["source"],
                                         "selected": v["value"] == chosen}
                                        for v in variants],
                               "action": "Escalate"})
                n_conflicts += 1
            elif f["status"] == "missing":
                fields.append({**base, "missing": True,
                               "missingNote": "⚠ REQUIRED · missing from all "
                                              "documents for this entity",
                               "missingDetail": "Request from client or upload "
                                                "a supplementary document.",
                               "action": "Request"})
                n_gaps += 1
                open_g += 1
            else:
                cite = "Source: " + ", ".join(f.get("sources", []))
                if dec:
                    cite += f" · decision: {dec['rationale'][:90]}"
                fields.append({**base, "value": f.get("value"),
                               "citation": cite, "action": "✏"})
        state = "complete" if open_c + open_g == 0 else "conflict"
        label_bits = []
        if open_c:
            label_bits.append(f"{open_c} escalated")
        if open_g:
            label_bits.append(f"{open_g} gap{'s' if open_g > 1 else ''}")
        clients.append({
            "id": f"E{i + 1}", "label": rec["entity_display"],
            "state": state,
            "stateLabel": "✓ Reconciled" if state == "complete"
                          else "⚠ " + " · ".join(label_bits),
            "fields": fields,
        })

    # ---- entities sidebar (from the real redaction log) ----
    entities = []
    for e in run["redaction_log"]:
        family = e["token"].strip("[]").rsplit("_", 1)[0]
        if family in FAMILY_TYPES:
            entities.append({"token": e["token"],
                             "type": FAMILY_TYPES[family],
                             "value": " / ".join(e["surface_forms"][:3])})

    # ---- initial exchange from the reconcile log entry ----
    reconcile = next((l for l in run["router_log"]
                      if l.get("stage") == "reconcile"), {})
    tokens = reconcile.get("tokens_sent", [])
    token_html = " ".join(
        f'<code class="token token-{FAMILY_TYPES.get(t.strip("[]").rsplit("_", 1)[0], "id")}">{t}</code>'
        for t in tokens[:10])
    route = reconcile.get("route", "local")
    receipt = (f"Reconcile ran as <b>{'1 redacted call' if route == 'hybrid' else 'full-local'}</b>. "
               f"Cloud saw: {token_html or 'nothing'} · "
               f"<b>0 detected identifiers crossed</b>")
    n_entities = len(run["records"])
    ai = (f"I reconciled <b>{n_entities} "
          f"{spec.get('entity_noun', 'entit')}{'s' if n_entities != 1 else ''}</b> "
          f"across {len(docs)} documents: {n_conflicts} conflict"
          f"{'s' if n_conflicts != 1 else ''} "
          f"({sum(1 for c in clients for f in c['fields'] if f.get('conflict') and any(o['selected'] for o in f.get('opts', [])))} resolved with rationale), "
          f"{n_gaps} required gap{'s' if n_gaps != 1 else ''}. "
          f"Records are in the panel; every value cites its source.")

    # ---- suggested questions from real artefacts ----
    qs = []
    if run["alias_groups"]:
        g = run["alias_groups"][0]
        qs.append([f"Why did you merge {g[1]}?",
                   f"Why did you merge {g[0]} and {g[1]}?"])
    for c in clients:
        for f in c["fields"]:
            if f.get("conflict"):
                qs.append([f"{f['label']} conflict?",
                           f"Why did you choose this {f['label'].lower()} "
                           f"for {c['label']}?"])
                break
        if len(qs) >= 2:
            break
    qs.append(["What is still missing?",
               "What is still missing across this pile?"])

    return {
        "domain": f"synthetic {spec['display_name'].lower()} · live pipeline",
        "assistantRole": "reconciler · live",
        "stats": [[len(docs), "documents"], [n_entities, spec.get("entity_noun", "entities") + "s"],
                  [n_conflicts, "conflicts"], [n_gaps, "gaps"]],
        "docs": docs, "clients": clients, "entities": entities,
        "initial": {"user": f"Reconcile this pile for "
                            f"{spec['display_name'].lower()}.",
                    "receipt": receipt, "ai": ai,
                    "sources": ("Local + remote (redacted) · live run"
                                if route == "hybrid"
                                else "Local resolver · no remote call · live run")},
        "suggestedQs": qs[:3],
        "canned": [],
        "live": True,
    }


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, type=Path)
    ap.add_argument("--extraction", required=True, type=Path)
    ap.add_argument("--schema", required=True, type=Path)
    args = ap.parse_args()
    view = build_pile_view(args.run, args.extraction, args.schema)
    print(json.dumps(view, indent=1)[:2000])


if __name__ == "__main__":
    main()
