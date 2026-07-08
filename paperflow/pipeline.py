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
# Field keys the extractor uses when the value is "who/what this doc is
# about". Checked in order under generic mode: the first key that maps
# to a real PERSON/ORG token wins. Beats scanning the redacted text
# because these keys are labelled by the extractor as the subject, not
# an incidental mention (a clinician on a patient intake is a bystander,
# even if the clinician's name repeats across the pile).
SUBJECT_FIELD_KEYS = [
    # ORG-labelled subject fields first: on partner/vendor docs both the
    # org and the contact person are labelled, but the doc is ABOUT the
    # org (the contact just happens to work there). Patient/KYC docs
    # don't have these keys, so they still fall through to the person
    # keys below.
    "organisation", "organization", "party_1_provider",
    "party_2_organiser", "party",
    # Personal-subject fields (patient/KYC docs, cardholder scans).
    "patient_name", "full_name", "cardholder", "applicant",
    "contact_name", "primary_contact", "name",
]

# Lowercase particles that are legitimately part of names in Malay,
# Indian, Arabic, Dutch, Portuguese, etc. — the shape filter has to let
# these through or it drops "Mohammed Farid bin Hassan", "Rajesh s/o
# Kumar", "Vincent van Gogh" as if they weren't names at all.
_NAME_PARTICLES = {"bin", "binte", "binti", "s/o", "d/o",
                   "van", "von", "der", "den", "de", "del", "della",
                   "di", "da", "du", "la", "le"}
# spaCy false-positives spot-checked in the KYC pile: bureaucratic
# phrasings that always match its PERSON classifier. The alias filter
# below is the primary line of defence; this is just a fast reject.
_NAME_REJECT_TOKENS = {"kyc", "aml", "cft", "nric", "fin", "uen",
                        "acra", "moh", "mas", "ica", "ecg", "hba1c",
                        "crp", "receipt", "invoice", "stub", "payment",
                        "statement", "reference", "previous", "current"}


def _looks_like_name(value: str) -> bool:
    """True if a token's canonical value reads as a personal name.
    Guards against spaCy PERSON false-positives like 'PAYMENT STUB' or
    'KYC/2026/05/00218' contaminating the entity-based grouping. Real
    person names contain only letters + a small set of punctuation,
    2-5 words, and titlecase everything except known particles."""
    if not value or any(ch.isdigit() or ch in "/@" for ch in value):
        return False
    words = value.split()
    if not (2 <= len(words) <= 5):
        return False
    for w in words:
        lw = w.lower()
        if lw in _NAME_REJECT_TOKENS:
            return False
        if lw in _NAME_PARTICLES:
            continue
        # non-particle words: must be title-cased and use only name-safe
        # characters (letters, apostrophe, hyphen, period for initials)
        if not w[0].isupper():
            return False
        if not all(ch.isalpha() or ch in "'-." for ch in w):
            return False
    return True


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
    generic = not schema_keys       # generic mode: no required fields at all
    records_raw: dict[str, dict[str, list]] = {}
    # DOC token counter — filenames themselves may carry PII
    # ("chloe_ng_nric.pdf"), so in generic mode we bucket per-doc records
    # under a sequential [DOC_N] identifier and keep the filename-to-token
    # map internal for the UI's source-citation column.
    doc_token_of: dict[str, str] = {}

    # Precompute per-doc PERSON/ORG tokens + a cross-doc frequency map,
    # so the ranked pick below can prefer entities that actually appear
    # in multiple docs (the client/patient/vendor) over letterheads that
    # appear only once (the doc's issuer). Old fallback grabbed the
    # first PERSON/ORG token per doc, which was always the letterhead.
    from collections import Counter
    doc_persons = {name: set(re.findall(r"\[PERSON_\d+\]", rtext))
                   for name, rtext in red.redacted.items()}
    doc_orgs = {name: set(re.findall(r"\[ORG_\d+\]", rtext))
                for name, rtext in red.redacted.items()}
    cross_doc: Counter = Counter()
    for toks in list(doc_persons.values()) + list(doc_orgs.values()):
        for t in toks:
            cross_doc[t] += 1

    def _rank_pick(doc_name: str) -> str | None:
        """Best PERSON/ORG token to key this doc's record on:
        1. Prefer PERSON tokens whose canonical value passes the
           name-shape filter (kills spaCy false-positives like 'PAYMENT
           STUB', 'KYC/2026/…', 'Statement Date').
        2. Break ties by cross-doc frequency — a token in 3 docs is the
           subject; a token in 1 doc is a bystander/letterhead.
        3. Fall back to ORG (same frequency ranking) only if no valid
           PERSON. No shape filter on ORG because real org names can
           be all-caps ('DBS Private') and the frequency ranking
           already suppresses letterhead false-positives.
        Returns None if the doc has neither → caller allocates DOC_N."""
        persons = [t for t in doc_persons.get(doc_name, ())
                   if _looks_like_name(emap.token_to_value.get(t, ""))]
        if persons:
            persons.sort(key=lambda t: (-cross_doc[t], t))
            return persons[0]
        orgs = sorted(doc_orgs.get(doc_name, ()),
                      key=lambda t: (-cross_doc[t], t))
        return orgs[0] if orgs else None

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
        # in generic mode all fields COULD feed the map (there are no schema
        # keys to gate on) but only if the field key or the value shape looks
        # like a real identifier. Unknown labels ('Prize pool', 'thehype')
        # would otherwise pile up as SERIAL tokens and clutter the entity
        # panel with non-entities. Presidio-detected values are already in
        # the map at this point (from the text-scan pass), so skipping the
        # unrecognized extractor labels does not shrink the redaction map.
        for key, value in fields.items():
            if key in schema_keys:
                emap.add(value, _family_for(key, value) or "SERIAL")
            elif generic:
                fam = _family_for(key, value)
                if fam:
                    emap.add(value, fam)

        ent_value = fields.get(entity_field)
        etoken = emap.token_of(ent_value) if ent_value else None
        if etoken is None and generic:
            # Generic-mode subject-field lookup: the extractor labels the
            # subject explicitly ("patient_name", "full_name",
            # "organisation"). Trust that over anything the redacted-text
            # scan can infer. Skip tokens that failed the name-shape
            # filter — the extractor sometimes emits phrasal labels.
            for sk in SUBJECT_FIELD_KEYS:
                v = fields.get(sk)
                if not v:
                    continue
                t = emap.token_of(v)
                if t and t.startswith(("[PERSON_", "[ORG_")):
                    if t.startswith("[PERSON_") and \
                            not _looks_like_name(emap.token_to_value.get(t, "")):
                        continue
                    etoken = t
                    break
        if etoken is None:
            # Fallback: ranked pick over PERSON/ORG tokens in the
            # redacted text. Cross-doc frequency + name-shape filter
            # keep letterheads and label false-positives out of the
            # bucketing key.
            etoken = _rank_pick(doc["doc"])
        if etoken is None:
            if generic:
                # No shared entity found → key on a sequential DOC token
                # (never the filename; filenames may embed PII, e.g.
                # chloe_ng_nric.pdf).
                if doc["doc"] not in doc_token_of:
                    doc_token_of[doc["doc"]] = f"[DOC_{len(doc_token_of) + 1}]"
                etoken = doc_token_of[doc["doc"]]
            else:
                etoken = "[UNASSIGNED]"
        bucket = records_raw.setdefault(etoken, {})
        for key, value in fields.items():
            if generic or key in schema_keys:
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

    # 4. audit: required fields missing everywhere for an entity = gap.
    # gap_when: negative treats "No"/"unsigned" as substantively missing
    # (the required action has not happened even though a value exists).
    NEGATIVE = re.compile(
        r"^[\(\[\-\*_\s]*"                                # leading punctuation
        r"(no|not\s+signed|unsigned|pending|nil|not\s+yet.*"
        r"|awaiting.*|outstanding|tbc|tbd|missing|awaiting\s+signature)"
        r"[\)\]\-\*_\s\.\!]*$", re.I)
    negative_keys = {f["key"] for f in spec["required_fields"]
                     if f.get("gap_when") == "negative"}
    for etoken, fields_ in records.items():
        for key in schema_keys:
            if key not in fields_:
                fields_[key] = {"value": None, "sources": [], "status": "missing",
                                "variants": []}
            elif key in negative_keys and fields_[key].get("value") \
                    and NEGATIVE.match(str(fields_[key]["value"]).strip()):
                fields_[key]["status"] = "missing"
                fields_[key]["note"] = (f"recorded as "
                                        f"'{fields_[key]['value']}': the "
                                        f"required action is outstanding")

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
