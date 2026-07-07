"""The privacy round-trip: detect -> consistent map -> redact -> re-hydrate.

Pile-wide propagation: once a value is detected anywhere in the pile, its
occurrences are redacted in every document via the map, even where the
detector missed that instance. This is what makes the map "consistent" and
also lifts recall.
"""
from __future__ import annotations

from dataclasses import dataclass

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

from .entity_map import EntityMap
from .recognisers import get_recognisers

_NLP_CONF = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
}

BUILTIN_ENTITIES = ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "LOCATION", "ORGANIZATION"]

# Form-label words that NER mistakes for entities in pipe-separated text.
LABEL_STOPWORDS = {
    "phone", "email", "name", "contact", "organisation", "organization",
    "company", "address", "uen", "fax", "website", "date", "rsvp", "status",
    "doc", "id", "doc id", "subject", "sent", "from", "to", "nric", "fin",
}

# Labelled form fields: these documents ARE forms, so the label is signal.
# Group 1 captures the value; a post-filter rejects non-name-like captures.
import re  # noqa: E402

# name characters: ASCII + Latin-1 letters (French, German, Nordic...),
# apostrophes (O'Connor) and hyphens (Jean-Pierre). Labels may be wrapped
# in markdown emphasis (**Full Name:** value).
_NC = r"A-Za-zÀ-ÖØ-öø-ÿ"
_PERSON_LABELS = re.compile(
    r"(?im)\b(?:account holder|cardholder|patient name|contact name|full name|"
    r"primary contact|patient|contact|applicant|name|referral)"
    r"[*_]*[ \t]*[:|\-–][*_]*[ \t]*"
    rf"([{_NC}][{_NC}.'-]*(?:[ \t]+(?:bin|binte|s/o|d/o|[{_NC}][{_NC}.'-]*)){{0,4}})")

_ORG_LABELS = re.compile(
    r"(?im)\b(?:organisation|organization|company|employer|partner)"
    r"[*_]*[ \t]*[:|\-–][*_]*[ \t]*"
    rf"([{_NC}][{_NC}&.'-]*(?:[ \t]+[{_NC}&.'-]+){{0,4}})")

_ORG_SUFFIX = re.compile(
    r"\b([A-Z][A-Za-z&]*(?:\s+[A-Za-z&]+){0,3}\s+(?:Pte\.?\s+Ltd\.?|LLP|Ltd\.?|Inc\.?|Limited))\b")


def _name_like(v: str) -> bool:
    return bool(v) and "@" not in v and not any(ch.isdigit() for ch in v) and 2 <= len(v.split()) <= 5


def scan_labelled_fields(text: str) -> list[tuple[str, str]]:
    """(value, entity_type) pairs from form-label structure."""
    found = []
    for m in _PERSON_LABELS.finditer(text):
        v = m.group(1).strip().rstrip("|").strip()
        if _name_like(v):
            found.append((v, "PERSON"))
    for m in _ORG_LABELS.finditer(text):
        v = m.group(1).strip().rstrip("|").strip()
        if _name_like(v) or _ORG_SUFFIX.search(v or ""):
            found.append((v, "ORG"))
    for m in _ORG_SUFFIX.finditer(text):
        found.append((m.group(1).strip(), "ORG"))
    return found


@dataclass
class RedactionResult:
    redacted: dict[str, str]      # doc name -> redacted text
    entity_map: EntityMap
    detections: dict[str, list]   # doc name -> raw analyzer results


class PrivacyRoundTrip:
    def __init__(self) -> None:
        nlp_engine = NlpEngineProvider(nlp_configuration=_NLP_CONF).create_engine()
        self.analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
        for rec in get_recognisers():
            self.analyzer.registry.add_recognizer(rec)
        custom = {r.supported_entities[0] for r in get_recognisers()}
        self.entities = sorted(set(BUILTIN_ENTITIES) | custom)

    def process_pile(self, docs: dict[str, str]) -> RedactionResult:
        entity_map = EntityMap()
        detections: dict[str, list] = {}

        # pass 1: detect and register every value across the whole pile
        for name, text in docs.items():
            results = self.analyzer.analyze(text=text, language="en",
                                            entities=self.entities)
            detections[name] = results
            # higher-score detections first so overlapping spans resolve
            # to the more specific recogniser
            for r in sorted(results, key=lambda r: -r.score):
                value = text[r.start:r.end].strip()
                # newline-spanning NER spans are label bleed, not entities
                if "\n" in value:
                    continue
                if len(value) >= 2 and value.lower() not in LABEL_STOPWORDS:
                    entity_map.add(value, r.entity_type)
            # labelled form fields catch what NER misses on non-Western names
            for value, etype in scan_labelled_fields(text):
                entity_map.add(value, etype)

        # pass 2: redact every document with the completed pile-wide map
        redacted = {name: entity_map.redact(text) for name, text in docs.items()}
        return RedactionResult(redacted=redacted, entity_map=entity_map,
                               detections=detections)
