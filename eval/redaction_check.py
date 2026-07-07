#!/usr/bin/env python3
"""Redaction acceptance test (the redaction-recall row of the scorer).

For every synthetic pile:
1. every ground-truth sensitive_span value is ABSENT from the redacted text
2. alias variations share ONE token with their canonical form
3. rehydrate(redact(text)) restores every span (round-trip is lossless
   up to alias canonicalisation)
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paperflow.ingest import load_pile           # noqa: E402
from paperflow.privacy.redactor import PrivacyRoundTrip  # noqa: E402

SYN = Path(__file__).resolve().parent.parent / "synthetic"


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower())


def main() -> int:
    rt = PrivacyRoundTrip()
    failures = 0

    for pile_dir in sorted(p for p in SYN.iterdir() if p.is_dir()):
        gt = json.loads((pile_dir / "ground_truth.json").read_text())
        docs = load_pile(pile_dir)
        result = rt.process_pile(docs)
        all_redacted = squash(" ".join(result.redacted.values()))

        print(f"\n=== {pile_dir.name} ===")

        # 1. spans absent from redacted text
        for span in gt["sensitive_spans"]:
            leaked = squash(span["value"]) in all_redacted
            failures += leaked
            print(f"  {'✗ LEAKED' if leaked else '✓'} [{span['type']}] {span['value']}")

        # 2. alias groups share one token
        for group in gt["alias_variations"]:
            tokens = set()
            for v in [group["canonical"], *group["aliases"]]:
                tokens.add(result.entity_map.token_of(v) or "<UNDETECTED>")
            ok = len(tokens) == 1 and "<UNDETECTED>" not in tokens
            failures += not ok
            print(f"  {'✓' if ok else '✗ SPLIT'} alias group {group['canonical']}: {tokens}")

        # 3. round-trip restores spans (canonical form counts for aliases)
        rehydrated = squash(" ".join(
            result.entity_map.rehydrate(t) for t in result.redacted.values()))
        aliases = {a for g in gt["alias_variations"] for a in g["aliases"]}
        for span in gt["sensitive_spans"]:
            if span["value"] in aliases:
                continue  # aliases legitimately restore as canonical
            lost = squash(span["value"]) not in rehydrated
            failures += lost
            if lost:
                print(f"  ✗ LOST IN ROUND-TRIP: {span['value']}")

        n_tokens = len(result.entity_map.token_to_value)
        print(f"  map: {n_tokens} tokens · {len(result.entity_map.values())} values")

    print(f"\n{'ALL CHECKS PASS' if failures == 0 else f'{failures} FAILURES'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
