#!/usr/bin/env python3
"""Stress test: a larger pile with adversarial reconciliation cases.

Generates a seeded ~36-doc KYC-style pile (12 clients x 3 docs) with known
ground truth, then scores the privacy round-trip and reconciler on:
  - redaction recall at scale
  - alias merging (chains: full name -> middle-drop -> initials)
  - FALSE-merge traps (similar names/IDs belonging to different people)
  - multi-way conflicts and gaps
  - wall time

No GPU needed: extraction is simulated from the generator's own field data
(extraction quality is measured separately by the floor test).
"""
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paperflow.privacy.redactor import PrivacyRoundTrip   # noqa: E402
from paperflow.reconciler import Reconciler               # noqa: E402

random.seed(42)

FIRST = ["Wei Ming", "Jia Hui", "Rajesh", "Ramesh", "Nurul", "Siti", "Marcus",
         "Yvonne", "Chloe", "Ahmad", "Kumar", "Mei Ling"]
LAST = ["Tan", "Lim", "Kumar", "Goh", "Aisyah", "Hassan", "Ng", "Lee",
        "Wong", "Rahman", "Pillai", "Chua"]
STREETS = ["Bishan St 23", "Tampines Ave 4", "Yishun Ring Rd", "Clementi Ave 2",
           "Hougang Ave 8", "Punggol Field"]


def make_nric(i: int) -> str:
    return f"S{7000000 + i * 13579 % 999999:07d}{'ABCDEFGHIZ'[i % 10]}"


def ocr_corrupt(nric: str) -> str:
    # swap one digit for a look-alike letter (5->S, 0->O, 1->I)
    for d, l in [("5", "S"), ("0", "O"), ("1", "I")]:
        idx = nric.find(d, 1)
        if idx > 0:
            return nric[:idx] + l + nric[idx + 1:]
    return nric[:-1] + "X"


def initials(name: str) -> str:
    parts = name.split()
    return f"{parts[0][0]}. {parts[-1]}"


def middle_drop(name: str) -> str:
    parts = name.split()
    return f"{parts[0]} {parts[-1]}" if len(parts) > 2 else name


def main() -> int:
    clients, docs, gt = [], {}, {
        "spans": set(), "alias_groups": [], "no_merge_pairs": [],
        "conflicts": [], "gaps": []}

    for i in range(12):
        name = f"{FIRST[i]} {LAST[i]}"
        nric = make_nric(i)
        addr = f"Blk {100 + i * 37} {STREETS[i % 6]} #{i + 2:02d}-{i * 7 % 90 + 10:02d}"
        c = {"id": f"C{i}", "name": name, "nric": nric, "addr": addr,
             "date": f"2026-0{i % 6 + 1}-{i % 27 + 1:02d}",
             "funds": "Employment income" if i % 3 else None}   # every 3rd: gap
        clients.append(c)
        gt["spans"] |= {name, nric}
        if c["funds"] is None:
            gt["gaps"].append((c["id"], "source_of_funds"))

    # adversarial alias chains for even clients: full -> middle-drop -> initials
    # (ordered, deterministic; every alias in gt must appear in some document)
    for c in clients[::2]:
        aliases = [a for a in dict.fromkeys([middle_drop(c["name"]),
                                             initials(c["name"])])
                   if a != c["name"]]
        if aliases:
            gt["alias_groups"].append([c["name"], *aliases])
            gt["spans"] |= set(aliases)
        c["aliases"] = aliases

    # false-merge traps: Rajesh vs Ramesh Kumar (i=2 vs 3 share last name),
    # and one-edit-apart NRICs across DIFFERENT people
    gt["no_merge_pairs"].append((clients[2]["name"], clients[3]["name"]))
    clients[4]["nric"] = clients[5]["nric"][:-1] + "Q"
    gt["spans"] |= {clients[4]["nric"], clients[5]["nric"]}
    gt["no_merge_pairs"].append((clients[4]["nric"], clients[5]["nric"]))

    # conflicts: odd clients get an OCR-corrupted NRIC on the scan doc;
    # client 1 gets a THREE-way address conflict
    for c in clients[1::2]:
        c["nric_scan"] = ocr_corrupt(c["nric"])
        gt["spans"].add(c["nric_scan"])
        gt["conflicts"].append((c["id"], "national_id", c["nric"]))
    c1 = clients[1]
    c1["addr2"] = c1["addr"].replace("Blk", "Block")          # format drift, same place
    c1["addr3"] = f"Blk 999 {STREETS[5]} #01-01"              # genuinely different
    gt["spans"].add(c1["addr3"])
    gt["conflicts"].append((c1["id"], "residential_address", None))  # escalate ok

    # ---- render docs (txt, form-styled like the demo piles) ----
    for i, c in enumerate(clients):
        form = (f"KYC Application Form\nDoc ID: form_{c['id']}\n"
                f"Full Name: {c['name']}\nNational ID: {c['nric']}\n"
                f"Residential Address: {c['addr']}\n"
                f"Declaration Date: {c['date']}\n")
        if c["funds"]:
            form += f"Source of Funds: {c['funds']}\n"
        docs[f"form_{c['id']}.txt"] = form

        display = c.get("aliases", [c["name"]])[0] if c.get("aliases") else c["name"]
        addr = c.get("addr3") if c.get("addr3") else c["addr"]
        docs[f"bill_{c['id']}.txt"] = (
            f"Utility Statement\nDoc ID: bill_{c['id']}\n"
            f"Account Holder: {display}\nService Address: {addr}\n")

        scan_nric = c.get("nric_scan", c["nric"])
        # the LAST alias (initials form) goes on the scan; aliases[0]
        # (middle-drop) went on the bill, so every gt alias is rendered
        scan_name = c["aliases"][-1] if c.get("aliases") else c["name"]
        extra = f"Registered Address: {c.get('addr2', c['addr'])}\n" if c.get("addr2") else ""
        docs[f"scan_{c['id']}.txt"] = (
            f"ID Copy (NRIC)\nDoc ID: scan_{c['id']}\n"
            f"Name: {scan_name}\nNational ID: {scan_nric}\n{extra}")

    print(f"pile: {len(docs)} docs · {len(clients)} clients · "
          f"{len(gt['spans'])} sensitive values")

    # ---- 1. privacy round-trip at scale ----
    t0 = time.time()
    rt = PrivacyRoundTrip()
    red = rt.process_pile(docs)
    t_redact = time.time() - t0
    emap = red.entity_map
    all_red = re.sub(r"\s+", " ", " ".join(red.redacted.values()).lower())

    leaks = [s for s in gt["spans"] if re.sub(r"\s+", " ", s.lower()) in all_red]
    alias_ok = sum(1 for g in gt["alias_groups"]
                   if len({emap.token_of(v) for v in g} - {None}) == 1
                   and None not in {emap.token_of(v) for v in g})
    false_merges = [(a, b) for a, b in gt["no_merge_pairs"]
                    if emap.token_of(a) is not None
                    and emap.token_of(a) == emap.token_of(b)]

    print(f"\n1. REDACTION  ({t_redact:.1f}s, {len(emap.token_to_value)} tokens)")
    print(f"   recall: {len(gt['spans']) - len(leaks)}/{len(gt['spans'])}"
          + (f"  LEAKED: {leaks}" if leaks else ""))
    print(f"   alias chains merged: {alias_ok}/{len(gt['alias_groups'])}")
    print(f"   false merges: {len(false_merges)}"
          + (f"  {false_merges}" if false_merges else "  (none, traps held)"))

    # ---- 2. reconciler at scale (simulated extraction from doc truth) ----
    records_raw: dict = {}
    for i, c in enumerate(clients):
        etoken = emap.token_of(c["name"]) or f"[PERSON_X{i}]"
        b = records_raw.setdefault(etoken, {})
        b["full_name"] = [(f"form_{c['id']}.txt", c["name"])]
        b["national_id"] = [(f"form_{c['id']}.txt", c["nric"])]
        if c.get("nric_scan"):
            b["national_id"].append((f"scan_{c['id']}.txt", c["nric_scan"]))
        b["residential_address"] = [(f"form_{c['id']}.txt", c["addr"])]
        if c.get("addr2"):
            b["residential_address"].append((f"scan_{c['id']}.txt", c["addr2"]))
        if c.get("addr3"):
            b["residential_address"].append((f"bill_{c['id']}.txt", c["addr3"]))
        if c["funds"]:
            b["source_of_funds"] = [(f"form_{c['id']}.txt", c["funds"])]

    t0 = time.time()
    rec = Reconciler(full_local=True)
    schema_keys = ["full_name", "national_id", "residential_address",
                   "declaration_date", "source_of_funds"]
    records, conflicts = rec.detect_conflicts(records_raw, schema_keys, emap)
    decisions = rec.decide("stress", conflicts)
    t_rec = time.time() - t0

    correct = wrong = escalated = 0
    for d in decisions:
        want = next((v for cid, k, v in gt["conflicts"]
                     if k == d.field_key and
                     emap.token_of(next(c["name"] for c in clients if c["id"] == cid))
                     == d.entity_token), "SKIP")
        if want == "SKIP":
            continue
        if d.escalate or d.chosen_token is None:
            escalated += 1
        elif want is None:
            wrong += 1  # should have escalated (no decisive evidence)
        elif emap.rehydrate(d.chosen_token) == want:
            correct += 1
        else:
            wrong += 1

    gaps_found = sum(
        1 for cid, key in gt["gaps"]
        if key not in records.get(emap.token_of(
            next(c["name"] for c in clients if c["id"] == cid)) or "?", {}))

    print(f"\n2. RECONCILER  ({t_rec:.2f}s, {len(conflicts)} conflicts detected, "
          f"expected {len(gt['conflicts'])})")
    print(f"   resolved correctly: {correct} · wrong: {wrong} · escalated: {escalated}")
    print(f"   gaps: {gaps_found}/{len(gt['gaps'])} (absent-field check)")

    failures = len(leaks) + len(false_merges) + wrong + \
        (len(gt["alias_groups"]) - alias_ok)
    print(f"\n{'STRESS PASS' if failures == 0 else f'{failures} STRESS FAILURES'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
