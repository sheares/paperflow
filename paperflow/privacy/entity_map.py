"""The consistent entity map: one real-world entity, one token, everywhere.

Design rules (from the build plan):
- Alias resolution runs BEFORE token assignment, so "Farid Hassan" and
  "Mohammed Farid bin Hassan" share [PERSON_1].
- Distinct observed values of a conflicting field keep distinct tokens
  ([ID_2] vs [ID_3]): the conflict is the payload, only identity is masked.
- The map never leaves the machine; it is serialised beside the pile and
  reversed by the Emitter.
- Session-scoped: tokens reset per pile.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# detector entity type -> token family
FAMILIES = {
    "PERSON": "PERSON",
    "ORG": "ORG",
    "ORGANIZATION": "ORG",
    "SG_NRIC": "ID",
    "SG_NRIC_SUSPECT": "ID",
    "SG_UEN": "UEN",
    "POLICY_NUMBER": "POLICY",
    "SERIAL": "SERIAL",
    "SG_PHONE": "PHONE",
    "PHONE_NUMBER": "PHONE",
    "EMAIL_ADDRESS": "EMAIL",
    "SG_ADDRESS": "ADDR",
    "LOCATION": "ADDR",
    "SG_POSTCODE": "POSTCODE",
    "ISO_DATE": "DATE",
    "DATE_TIME": "DATE",
}

_ORG_SUFFIX_RE = re.compile(r"\s+(?:pte\.?\s+ltd\.?|llp|ltd\.?|inc\.?|limited|llc)$", re.I)


def _words(value: str) -> list[str]:
    return [w for w in re.split(r"[^\w.]+", value.lower()) if w]


def _person_alias(a: str, b: str) -> bool:
    """True if the shorter name reads as an alias of the longer one: every
    word matches a word (or the initial of a word) in the longer name, with
    at least one shared full word of length >= 4."""
    wa, wb = _words(a), _words(b)
    short, long_ = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    if not short or short == long_:
        return False
    shared_full = False
    for w in short:
        core = w.rstrip(".")
        if len(core) == 1:  # an initial such as "r."
            if not any(lw.startswith(core) for lw in long_):
                return False
        elif w in long_:
            shared_full = shared_full or len(w) >= 4
        else:
            return False
    return shared_full


def _org_alias(a: str, b: str) -> bool:
    sa = {w for w in _words(_ORG_SUFFIX_RE.sub("", a))}
    sb = {w for w in _words(_ORG_SUFFIX_RE.sub("", b))}
    if not sa or not sb or a.lower() == b.lower():
        return False
    smaller, bigger = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    return smaller <= bigger and any(len(w) >= 4 for w in smaller)


@dataclass
class EntityMap:
    token_to_value: dict[str, str] = field(default_factory=dict)   # token -> canonical value
    _lookup: dict[str, str] = field(default_factory=dict)          # lower(value) -> token
    _display: dict[str, str] = field(default_factory=dict)         # lower(value) -> as first seen
    _counters: dict[str, int] = field(default_factory=dict)

    def token_of(self, value: str) -> str | None:
        return self._lookup.get(value.strip().lower())

    def values(self) -> list[str]:
        return list(self._display.values())

    def add(self, value: str, entity_type: str) -> str:
        """Register a detected value; returns its token (existing or new)."""
        value = value.strip()
        key = value.lower()
        if key in self._lookup:
            return self._lookup[key]
        family = FAMILIES.get(entity_type, entity_type)

        # alias resolution: reuse the token of an existing alias in the family
        for known_key, token in self._lookup.items():
            if not token.startswith(f"[{family}_"):
                continue
            known = self._display[known_key]
            if (family == "PERSON" and _person_alias(value, known)) or \
               (family == "ORG" and _org_alias(value, known)):
                self._register(key, value, token)
                return token

        self._counters[family] = self._counters.get(family, 0) + 1
        token = f"[{family}_{self._counters[family]}]"
        self.token_to_value[token] = value
        self._register(key, value, token)

        # orgs: also map the suffix-stripped core ("Acme Robotics Pte Ltd"
        # -> "Acme Robotics"), so brand-style mentions redact to the same token
        if family == "ORG":
            core = _ORG_SUFFIX_RE.sub("", value).strip()
            if core.lower() != key and len(core) >= 4:
                self._register(core.lower(), core, token)
        return token

    def _register(self, key: str, display: str, token: str) -> None:
        self._lookup[key] = token
        self._display[key] = display

    def redact(self, text: str) -> str:
        """Replace every mapped value in ONE pass (longest-first alternation,
        case-insensitive). A single pass means a later value can never match
        inside an already-inserted token."""
        if not self._lookup:
            return text
        pattern = re.compile("|".join(
            re.escape(self._display[k])
            for k in sorted(self._lookup, key=len, reverse=True)), re.IGNORECASE)
        return pattern.sub(lambda m: self._lookup[m.group(0).lower()], text)

    def rehydrate(self, text: str) -> str:
        # longest token first: plain replace of [PHONE_1] must never eat
        # the prefix of [PHONE_10]
        for token in sorted(self.token_to_value, key=len, reverse=True):
            text = text.replace(token, self.token_to_value[token])
        return text

    def to_json(self) -> str:
        return json.dumps({
            "token_to_value": self.token_to_value,
            "lookup": self._lookup,
            "display": self._display,
        }, indent=1)

    @classmethod
    def from_json(cls, raw: str) -> "EntityMap":
        d = json.loads(raw)
        m = cls(token_to_value=d["token_to_value"],
                _lookup=d["lookup"], _display=d["display"])
        for token in m.token_to_value:
            family, n = token.strip("[]").rsplit("_", 1)
            m._counters[family] = max(m._counters.get(family, 0), int(n))
        return m
