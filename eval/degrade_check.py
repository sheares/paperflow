#!/usr/bin/env python3
"""Remote-outage degradation: with a broken FIREWORKS_API_KEY the pipeline
and router must fall back to local rules gracefully, log the degradation
honestly, and never crash a request."""
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["FIREWORKS_API_KEY"] = "INVALID_KEY_ON_PURPOSE"

from paperflow.pipeline import run_pile      # noqa: E402
from paperflow.router import Router          # noqa: E402


def main() -> int:
    tmp = Path("/tmp/pf_degrade")
    shutil.rmtree(tmp, ignore_errors=True)
    run_pile(Path("synthetic/kyc_onboarding"),
             Path("paperflow/schemas/kyc.yaml"),
             cached_extraction=Path("outputs/extraction_kyc_onboarding.json"),
             full_local=False, out_root=tmp)

    d = json.load(open(tmp / "run_kyc_onboarding" / "run_output.json"))
    log = d["router_log"][0]
    checks = [
        ("pipeline completed despite bad key", True),
        ("router log recorded route=local after degrade",
         log["route"] == "local"),
        ("router log honestly mentions 'remote unavailable' or 'degraded'",
         "degraded" in log["reason"] or "unavailable" in log["reason"]),
        ("no tokens crossed on the failed remote attempt",
         log["tokens_sent"] == []),
        ("conflicts still received a decision (local rules)",
         all(f.get("decision") for r in d["records"]
             for f in r["fields"].values()
             if f["status"] in {"resolved_conflict", "escalated"})),
    ]

    r = Router(tmp / "run_kyc_onboarding")
    # a fresh cross-doc question that would normally go hybrid: with a bad
    # key, the Router must degrade to the local artefact path
    res = r.ask("What is the current AML posture across the pile?",
                full_local=False)
    checks += [
        ("router.ask degraded to local when remote fails",
         res["log_entry"]["route"] == "local"),
        ("router.ask returned a non-empty answer even after degrade",
         bool(res["answer"])),
        ("degraded receipt says 0 cloud calls",
         res["receipt"]["chip"] == "Local only · 0 cloud calls"),
    ]

    shutil.rmtree(tmp, ignore_errors=True)
    failed = 0
    for name, ok in checks:
        print(f"  {'✓' if ok else '✗ FAIL'} {name}")
        failed += not ok
    print("DEGRADE PASS" if failed == 0 else f"{failed} DEGRADE FAILURES")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
