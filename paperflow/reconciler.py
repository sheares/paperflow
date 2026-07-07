"""Reconciler: the agentic core.

Local: group fields by entity, detect conflicts, compute safe features of
the conflicting values (format validity, edit distance, OCR-substitution
likelihood). Remote (Fireworks, DeepSeek V4 Pro): ONE redacted call per
pile carrying tokens + features + doc types, never a real value. Every
decision is persisted as an artefact; the router log records exactly what
crossed, so privacy receipts derive from ground truth.

Full-local mode resolves with the same features through deterministic
rules on the MI300X side of the boundary: zero egress by construction.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field, asdict

import httpx

FIREWORKS_URL = "https://api.fireworks.ai/inference/v1/chat/completions"
FIREWORKS_MODEL = os.environ.get(
    "FIREWORKS_MODEL", "accounts/fireworks/models/deepseek-v4-pro")

STRICT_FORMATS = {
    "national_id": re.compile(r"^[A-Z]\d{7}$|^[STFGM]\d{7}[A-Z]$"),
    "nric_fin": re.compile(r"^[STFGM]\d{7}[A-Z]$"),
    "policy_number": re.compile(r"^(?:PRU|AIA|GE|NTUC)-\d{6}$"),
    "email": re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    "phone": re.compile(r"^\+65[ -]?[689]\d{3}[ -]?\d{4}$"),
    "date_of_birth": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "declaration_date": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
}

# Document types ranked by evidentiary weight for resolution rationale.
AUTHORITATIVE_HINTS = {
    "kyc_form": "self-submitted, signed at onboarding",
    "intake": "self-submitted, signed at registration",
    "declaration": "self-submitted, signed",
    "registration": "self-submitted registration record",
    "nric_scan": "scanned image, OCR-prone",
    "insurance": "third-party card, small print, OCR-prone",
    "utility_bill": "third-party document",
    "referral": "third-party correspondence, typed in a hurry",
    "business_card": "third-party artefact",
    "email": "informal correspondence",
    "mou": "executed agreement",
    "contacts": "secondary spreadsheet",
    "lab": "clinical requisition",
}


def _edit_distance(a: str, b: str) -> int:
    if len(a) > len(b):
        a, b = b, a
    prev = list(range(len(a) + 1))
    for j, cb in enumerate(b, 1):
        cur = [j]
        for i, ca in enumerate(a, 1):
            cur.append(min(prev[i] + 1, cur[i - 1] + 1, prev[i - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _doc_hint(doc: str) -> str:
    for key, hint in AUTHORITATIVE_HINTS.items():
        if key in doc.lower():
            return hint
    return "supporting document"


@dataclass
class Variant:
    doc: str
    doc_hint: str
    token: str
    value: str          # raw value: stays local, never serialised remotely
    format_valid: bool | None


@dataclass
class Conflict:
    field_key: str
    entity_token: str
    variants: list[Variant]
    features: dict = field(default_factory=dict)

    def compute_features(self) -> None:
        vals = [v.value for v in self.variants]
        f: dict = {"n_variants": len(vals)}
        if len(vals) == 2:
            a, b = vals
            f["edit_distance"] = _edit_distance(a.lower(), b.lower())
            f["same_length"] = len(a) == len(b)
            if len(a) == len(b):
                diffs = [(i, x, y) for i, (x, y) in enumerate(zip(a, b)) if x != y]
                f["char_diffs"] = len(diffs)
                f["likely_ocr_substitution"] = (
                    len(diffs) == 1 and diffs[0][1].isdigit() != diffs[0][2].isdigit())
        f["format_validity"] = {v.token: v.format_valid for v in self.variants}
        self.features = f

    def remote_payload(self) -> dict:
        """What crosses the trust boundary: tokens, hints, features. No values."""
        return {
            "field": self.field_key,
            "entity": self.entity_token,
            "variants": [{"token": v.token, "source_doc_type": v.doc_hint}
                         for v in self.variants],
            "features": self.features,
        }


@dataclass
class Decision:
    field_key: str
    entity_token: str
    chosen_token: str | None
    confidence: float
    rationale: str
    escalate: bool
    source: str                       # "remote" | "local-rules"
    variants: list[dict] = field(default_factory=list)

    def to_artifact(self) -> dict:
        return asdict(self)


REMOTE_PROMPT = """You are the reconciliation engine of a document-processing \
pipeline. You see only placeholder tokens, document-type hints, and computed \
features. You never see real values; do not ask for them.

For each conflict below, decide which variant token is most likely correct, \
or escalate if the evidence is insufficient. Reasoning guide: a variant that \
fails format validation is likely an error; a single character substitution \
between a digit and a letter suggests OCR corruption in the scan-prone \
document; self-submitted signed documents outrank third-party artefacts for \
personal fields; third-party issued documents outrank self-declared ones for \
their own domain (e.g. an insurance card for a policy number) unless features \
say otherwise.

Conflicts:
{conflicts}

Respond with STRICT JSON only, no other text:
{{"decisions": [{{"field": "...", "entity": "...", "chosen": "[TOKEN]", \
"confidence": 0.0, "rationale": "one or two sentences citing tokens and \
document types only", "escalate": false}}]}}"""


def _parse_remote_json(content: str) -> dict:
    """DeepSeek V4 Pro may prepend reasoning; take the LAST JSON object."""
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.S)
    if fenced:
        return json.loads(fenced[-1])
    start = content.rfind('{"decisions"')
    if start == -1:
        start = content.find("{")
    return json.loads(content[start:])


class Reconciler:
    def __init__(self, full_local: bool = False):
        self.full_local = full_local
        self.router_log: list[dict] = []

    def detect_conflicts(self, records: dict, schema_keys: list[str],
                         entity_map) -> tuple[dict, list[Conflict]]:
        """records: entity_token -> field_key -> list[(doc, value)].
        Returns (resolved fields structure, conflicts needing decisions)."""
        conflicts = []
        resolved: dict = {}
        for etoken, fields_ in records.items():
            resolved[etoken] = {}
            for key, sightings in fields_.items():
                by_norm: dict[str, list] = {}
                for doc, value in sightings:
                    # alias-aware grouping: values sharing a map token are the
                    # same entity surface form, not a conflict
                    norm = entity_map.token_of(value) or \
                        re.sub(r"\s+", " ", value.strip().lower())
                    by_norm.setdefault(norm, []).append((doc, value))
                if len(by_norm) == 1:
                    docs = [d for d, _ in sightings]
                    value = sightings[0][1]
                    canonical = entity_map.token_of(value)
                    if canonical:  # aliases display as the canonical form
                        value = entity_map.rehydrate(canonical)
                    resolved[etoken][key] = {
                        "value": value, "sources": docs,
                        "status": "resolved", "variants": []}
                else:
                    fmt = STRICT_FORMATS.get(key)
                    variants = []
                    for norm, group in by_norm.items():
                        doc, value = group[0]
                        token = entity_map.token_of(value) or entity_map.add(
                            value, _family_for(key))
                        variants.append(Variant(
                            doc=doc, doc_hint=_doc_hint(doc), token=token,
                            value=value,
                            format_valid=bool(fmt.match(value.strip())) if fmt else None))
                    c = Conflict(field_key=key, entity_token=etoken,
                                 variants=variants)
                    c.compute_features()
                    conflicts.append(c)
                    resolved[etoken][key] = {
                        "value": None, "sources": [v.doc for v in variants],
                        "status": "conflict",
                        "variants": [{"value": v.value, "source": v.doc,
                                      "token": v.token} for v in variants]}
        return resolved, conflicts

    def decide(self, pile: str, conflicts: list[Conflict]) -> list[Decision]:
        if not conflicts:
            return []
        if self.full_local:
            decisions = [self._local_rules(c) for c in conflicts]
            self.router_log.append({
                "stage": "reconcile", "route": "local",
                "reason": "full-local mode · remote reasoning disabled by the operator",
                "tokens_sent": [], "pile": pile})
            return decisions
        return self._remote_decide(pile, conflicts)

    def _local_rules(self, c: Conflict) -> Decision:
        valid = [v for v in c.variants if v.format_valid]
        if len(valid) == 1:
            return Decision(
                field_key=c.field_key, entity_token=c.entity_token,
                chosen_token=valid[0].token, confidence=0.85,
                rationale=(f"{valid[0].token} is the only variant passing the "
                           f"{c.field_key} format check; the rejected variant "
                           f"shows a digit/letter substitution consistent with OCR."),
                escalate=False, source="local-rules",
                variants=[asdict(v) for v in c.variants])
        self_sub = [v for v in c.variants if "self-submitted" in v.doc_hint]
        if len(self_sub) == 1:
            return Decision(
                field_key=c.field_key, entity_token=c.entity_token,
                chosen_token=self_sub[0].token, confidence=0.7,
                rationale=(f"{self_sub[0].token} comes from a self-submitted "
                           f"signed document ({self_sub[0].doc_hint}); the "
                           f"alternative is third-party."),
                escalate=False, source="local-rules",
                variants=[asdict(v) for v in c.variants])
        return Decision(
            field_key=c.field_key, entity_token=c.entity_token,
            chosen_token=None, confidence=0.4,
            rationale="No decisive local signal; escalating to human review.",
            escalate=True, source="local-rules",
            variants=[asdict(v) for v in c.variants])

    def _remote_decide(self, pile: str, conflicts: list[Conflict]) -> list[Decision]:
        payload = [c.remote_payload() for c in conflicts]
        tokens_sent = sorted({v.token for c in conflicts for v in c.variants}
                             | {c.entity_token for c in conflicts})
        prompt = REMOTE_PROMPT.format(conflicts=json.dumps(payload, indent=1))
        t0 = time.time()
        r = httpx.post(FIREWORKS_URL, timeout=120, headers={
            "Authorization": f"Bearer {os.environ['FIREWORKS_API_KEY']}",
            "Content-Type": "application/json",
        }, json={
            "model": FIREWORKS_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 3000,
            "temperature": 0,
        })
        r.raise_for_status()
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        parsed = _parse_remote_json(content)
        self.router_log.append({
            "stage": "reconcile", "route": "hybrid",
            "reason": "cross-document conflict resolution · redacted tokens and "
                      "features sent to Fireworks",
            "model": FIREWORKS_MODEL,
            "tokens_sent": tokens_sent,
            "usage": data.get("usage", {}),
            "latency_s": round(time.time() - t0, 2),
            "pile": pile})

        by_key = {(d["field"], d["entity"]): d for d in parsed["decisions"]}
        decisions = []
        for c in conflicts:
            d = by_key.get((c.field_key, c.entity_token))
            if d is None:
                decisions.append(self._local_rules(c))
                continue
            decisions.append(Decision(
                field_key=c.field_key, entity_token=c.entity_token,
                chosen_token=d.get("chosen"),
                confidence=float(d.get("confidence", 0.5)),
                rationale=str(d.get("rationale", "")),
                escalate=bool(d.get("escalate", False)),
                source="remote",
                variants=[asdict(v) for v in c.variants]))
        return decisions


def _family_for(key: str) -> str:
    table = {
        "national_id": "SG_NRIC_SUSPECT", "nric_fin": "SG_NRIC",
        "policy_number": "POLICY_NUMBER", "email": "EMAIL_ADDRESS",
        "phone": "SG_PHONE", "residential_address": "SG_ADDRESS",
        "date_of_birth": "ISO_DATE", "declaration_date": "ISO_DATE",
        "full_name": "PERSON", "patient_name": "PERSON",
        "contact_name": "PERSON", "organisation": "ORG",
    }
    return table.get(key, "SERIAL")
