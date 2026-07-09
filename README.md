# paperflow

**The document reconciler you can point at confidential paperwork, because
nothing has to leave your hardware.**

Drop in a pile of messy documents: scanned forms, spreadsheets, photos of
IDs. paperflow extracts every field with provenance, reconciles the values
that disagree across documents, flags what is missing against a required-
fields checklist, and emits a clean, verified record. Sensitive identifiers
are redacted with a consistent entity map before any cloud call and restored
afterwards; **air-gapped mode** runs the whole thing with zero egress.

📽️ **Demo video**: [link pending Thursday recording]
📊 **Deck** (PDF): [`docs/paperflow-pitch.pdf`](docs/paperflow-pitch.pdf) · source: [`docs/paperflow-pitch.html`](docs/paperflow-pitch.html)

## Why this exists

Privacy LLM gateways redact chat prompts, not document piles. Cloud IDP
reconciles documents, but in the vendor's cloud, exactly what a bank, clinic
or law firm under a cloud ban cannot use. paperflow serves the gap:
cross-document reconciliation for piles that legally cannot leave the
building, running on your own AMD hardware. Built for the AMD Developer
Hackathon ACT II (Unicorn track).

## How it works

```
┌─────────┐   ┌─────────┐   ┌───────────┐   ┌────────┐   ┌───────┐
│ Extract │──▶│ Resolve │──▶│ Reconcile │──▶│ Audit  │──▶│ Emit  │
│ Gemma   │   │ Presidio│   │ Fireworks │   │ local  │   │ local │
│ MI300X  │   │ + map   │   │ (tokens)  │   │        │   │       │
└─────────┘   └─────────┘   └───────────┘   └────────┘   └───────┘
   local        local         redacted        local       local
```

1. **Extractor** (local, **Gemma-4-31B-IT** on an AMD Instinct MI300X):
   fields with provenance and confidence, straight from raw documents.
2. **Entity resolver + redactor** (local, Microsoft Presidio + custom
   recognisers): merges aliases, builds one consistent map for the whole
   pile (`Acme Corp` = `ACME Corporation` = `[ORG_1]` everywhere), redacts.
3. **Reconciler** (remote on redacted tokens via Fireworks AI; defaults to
   Minimax M3, swap via `FIREWORKS_MODEL` env; sensitive comparisons stay
   local): finds conflicts, proposes resolutions with rationale, escalates
   the rest.
4. **Auditor** (local): gap-check against the pile's required-fields schema.
5. **Emitter** (local): re-hydrates from the map, emits the record and report.

The consistent map is the trick: because tokenisation is stable across
documents, the cloud model can reason about relationships between
placeholders without ever seeing a real value.

## The trust UI

Every exchange shows a **privacy receipt**: what the cloud saw (tokens only),
a routing chip ("Local only · 0 cloud calls" vs "Local + Cloud · 1 redacted
call"), and why it was routed that way, derived from the router's actual
log, never a template. A **pre-send review gate** requires explicit
confirmation before any message containing detected values goes out.
**Air-gapped mode** disables remote reasoning entirely (nothing crosses to
Fireworks).

The client renders the server's `receipt_from_log` projection directly, so
the receipt cannot be fabricated client-side — verified by `receipts_check`.
See slide 8 of [`docs/paperflow-pitch.html`](docs/paperflow-pitch.html) for
a visual of the receipt-in-context.

## Quickstart

```bash
git clone https://github.com/sheares/paperflow && cd paperflow
cp .env.example .env        # add your Fireworks key (optional in full-local mode)
docker compose up
# open http://localhost:8080, click "Load synthetic KYC pile"
```

Local models run on an AMD Instinct MI300X (ROCm) served by vLLM; point
`VLLM_URL` at your endpoint.

## Does it actually work? (eval)

Scored across three synthetic piles (15 documents, 7 real-world entities,
6 planted conflicts, 5 planted gaps, 3 alias groups, 38 sensitive spans),
reconciled by Fireworks Minimax M3 on redacted tokens:

| Task                | Score           | Notes |
| ------------------- | --------------- | ----- |
| Conflict detection  | **6 / 6 (100%)**   | every planted conflict flagged; also caught an unplanted RSVP divergence in partner_collation |
| Conflict resolution | **5 / 6 (83%)**    | one honest miss on a form-of-record vs. email-signature judgement for a phone number |
| Gap flagging        | **3 / 5 (60%)**    | two gaps that a stricter reconciler would flag as REQUIRED · not found got resolved to a fuzzy value instead ("not explicitly stated" for source of funds); mitigated in the product by the human-review pattern the trust UI surfaces |
| Alias resolution    | **3 / 3 (100%)**   | plus 15 unscored true alias merges the ground truth did not enumerate (letterhead expansions, UEN pairings) |
| Redaction recall    | **38 / 38 (100%)** | every planted sensitive span absent from the redacted corpus |

Reproduce with a Fireworks key present: `python -m eval.scorer`.
Reproduce fully offline (air-gapped, no cloud calls) via
`python -m paperflow.pipeline --full-local ...` and the same scorer.
Swap the cloud reasoner via `FIREWORKS_MODEL=deepseek` (recovers 5/5 gap
flagging at ~5.8× the per-call cost; Minimax M3 is the shipped default).

Additional harnesses in `eval/`, all green:
- `redaction_check.py`: pile-wide round-trip acceptance (spans absent,
  alias groups share one token, rehydration lossless)
- `stress_test.py`: adversarial reconciler harness — 10/10 conflicts
  correct, 1 designed escalation, 7/7 gaps caught
- `receipts_check.py`: receipts are pure projections of the router log
  (the client never fabricates a chip or a token count)
- `injection_check.py`: document-borne prompt injection contained
- `model_ab.py`: side-by-side Minimax M3 / DeepSeek V4 Pro / Qwen / GLM
  latency + cost + quality on the same tokenised prompt

Extractor floor test (measured on an MI300X, 2026-07-07): 15/15 synthetic
documents, effective planted-value recovery 50/50, ~5 s per vision page.

## AMD infrastructure

All raw-sensitive work runs on a single MI300X: the entire confidential
stack (**Gemma-4-31B-IT** extraction, local reconciliation heuristics,
Presidio-based redaction, and the entity map) is co-resident in the 192 GB
HBM3. paperflow is an **AMD-hosted Gemma project**: Gemma does the
raw-sensitive extraction on your own hardware, no real identity ever leaves
the card, and the cloud model only ever sees redacted, consistently-
tokenised text. In **air-gapped mode** the cloud model is not called at
all, and the router asserts `route == "local"` on the server side — the
zero-egress claim is true by construction, not by convention.

The droplet lifecycle (sleep/wake/tunnel/status) is scripted at
`scripts/droplet.sh` so the MI300X only accrues cost when it's actually
serving a demo; snapshot-restore takes ~5 min from cold and preserves the
loaded Gemma weights.

## Honest limits

Security rests on detection recall. Structured identifiers (NRICs, UENs,
policy numbers) are high-recall; person and company names rely on NER and
will miss edge cases. paperflow claims **sharply reduced exposure, not zero
leakage**; the detected-entities panel and the flag-a-missed-entity control
exist so you can audit and patch recall in real time. Absolute zero-egress
claims apply only to full-local mode, where they are true by construction.
Not certified against MAS, HIPAA or any other regime.

**Language scope: English documents only.** Any Latin-script name is in
scope (Singaporean, Anglo, European including accented forms); non-English
documents and non-Latin scripts are roadmap, requiring per-language NER
models (which Presidio supports) and translated field-label patterns.
Structured identifiers (NRICs, UENs, phones, emails) are script-agnostic
regexes and retain recall regardless of document language.

## Data

Synthetic only. Every name, ID and address in this repo and the demo is
generated (`generate_synthetic.py`); no real personal data anywhere.

## Licence

MIT. Built in 120 hours at the AMD Developer Hackathon ACT II, on AMD
Developer Cloud (MI300X, ROCm) and Fireworks AI.
