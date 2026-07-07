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
import unicodedata
from dataclasses import dataclass, field


def _fold(s: str) -> str:
    """Accent-fold: François -> Francois (clerks drop diacritics)."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()

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
    """Split a name into words. Hyphenated compound given names
    (Jean-Pierre) and apostrophe surnames (O'Connor) stay atomic, so
    "Jean Dubois" is NOT an alias of "Jean-Pierre Dubois"."""
    return [w.strip(".'-") or w for w in re.split(r"[^\w.'-]+", value.lower()) if w]


def _person_alias(a: str, b: str) -> bool:
    """True if either name reads as an alias (shortening) of the other.
    Both directions are tried: with equal word counts ("R. Kumar" vs
    "Rajesh Kumar") the alias direction is not knowable from length."""
    wa, wb = _words(a), _words(b)
    return _alias_of(wa, wb) or _alias_of(wb, wa)


def _alias_of(short: list[str], long_: list[str]) -> bool:
    """Every word of `short` matches a word (or the initial of a word) in
    `long_`, with at least one shared full word (>=3 letters, or a 2-letter
    surname in final position)."""
    if not short or short == long_:
        return False
    shared_full = False
    for w in short:
        core = w.rstrip(".")
        if len(core) == 1:  # an initial such as "r."
            if not any(lw.startswith(core) for lw in long_):
                return False
        elif w in long_:
            # a 3+ letter shared word counts; so does a 2-letter SURNAME
            # match in final position (Ng, Oh: common in Singapore)
            shared_full = shared_full or len(w) >= 3 or \
                (w == short[-1] == long_[-1] and len(w) >= 2)
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

        # accent-fold hit: "François Lefèvre" arriving after a typed
        # "Francois Lefevre" (or vice versa) is the same entity
        folded_key = _fold(value).lower()
        if folded_key != key and folded_key in self._lookup:
            token = self._lookup[folded_key]
            self._register(key, value, token)
            if value != _fold(value):     # diacritic form carries more info
                self.token_to_value[token] = value
            return token

        def _has_initial(n: str) -> bool:
            return any(len(w.rstrip(".")) == 1 for w in _words(n))

        # alias resolution: reuse the token of an existing alias in the family.
        # Only PERSON and ORG have string-similarity aliases; every other
        # family (ID, ADDR, DATE, EMAIL, PHONE, etc.) treats distinct strings
        # as distinct entities. Subword matching an address against another
        # address is a leak class ("Singapore" == "8 Marina ... Singapore").
        alias_families = {"PERSON", "ORG"}
        if family in alias_families:
            for known_key, token in self._lookup.items():
                if not token.startswith(f"[{family}_"):
                    continue
                known = self._display[known_key]
                if family == "PERSON":
                    canonical = self.token_to_value[token]
                    if _has_initial(known) and not _has_initial(value):
                        # a full name meeting an initials alias: merge only if
                        # the token is unclaimed (canonical still initials) or
                        # already claimed by a matching full name. "Ramesh
                        # Kumar" cannot bridge into a token Rajesh Kumar has
                        # claimed.
                        ok = (_person_alias(value, known)
                              if _has_initial(canonical)
                              else _person_alias(value, canonical))
                    else:
                        ok = _person_alias(value, known)
                else:
                    ok = _org_alias(value, known)
                if ok:
                    self._register(key, value, token)
                    # the fullest surface form is the canonical one
                    # (re-hydration restores "Tan Mei Ling", not a partial NER
                    # catch "Mei Ling")
                    if len(value) > len(self.token_to_value[token]):
                        self.token_to_value[token] = value
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
        # accent-folded twin: a doc typing "Francois" for "François" still
        # redacts to the same token
        folded = _fold(display)
        if folded and folded.lower() != key and folded.lower() not in self._lookup:
            self._lookup[folded.lower()] = token
            self._display[folded.lower()] = folded

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
