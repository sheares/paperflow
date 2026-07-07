#!/usr/bin/env python3
"""Receipts-vs-log consistency: the receipt shown must be a pure projection
of the router log entry. Runs against a persisted run directory; the local
route is exercised end-to-end (zero cloud calls by construction)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paperflow.router import Router, receipt_from_log   # noqa: E402

RUN = Path(__file__).resolve().parent.parent / "outputs" / "run_kyc_onboarding"


def main() -> int:
    if not RUN.exists():
        print("run_kyc_onboarding missing; run the pipeline first")
        return 1
    r = Router(RUN)
    failures = 0

    # 1. local route: alias question answered from artefacts, nothing crosses
    res = r.ask("Why did you merge Mohammed Farid bin Hassan and Farid Hassan?")
    e, receipt = res["log_entry"], res["receipt"]
    checks = [
        ("route is local", e["route"] == "local"),
        ("no tokens crossed", e["tokens_sent"] == []),
        ("no model in entry", "model" not in e),
        ("receipt == projection of log", receipt == receipt_from_log(e)),
        ("chip says 0 cloud calls", receipt["chip"] == "Local only · 0 cloud calls"),
        ("answer names the merge", "Farid" in res["answer"]),
        ("question redacted in log", "[PERSON_" in e["question_redacted"]
         and "Hassan" not in e["question_redacted"]),
    ]

    # 2. classification sanity
    checks += [
        ("merge question routes local", r.classify("why did you merge these?") == "local"),
        ("fresh question routes hybrid", r.classify("what is missing for AML?") == "hybrid"),
    ]

    # 3. full-local override forces local
    res2 = r.ask("what is missing for AML?", full_local=True)
    checks.append(("full-local forces local route",
                   res2["log_entry"]["route"] == "local"))

    for name, ok in checks:
        print(f"  {'✓' if ok else '✗ FAIL'} {name}")
        failures += not ok

    print("RECEIPTS PASS" if failures == 0 else f"{failures} RECEIPT FAILURES")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
