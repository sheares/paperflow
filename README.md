# paperflow

**The document reconciler you can point at confidential paperwork, because
nothing has to leave your hardware.**

Drop in a pile of messy documents: scanned forms, spreadsheets, photos of
IDs. paperflow extracts every field with provenance, reconciles the values
that disagree across documents, flags what is missing against a required-
fields checklist, and emits a clean, verified record. Sensitive identifiers
are redacted with a consistent entity map before any cloud call and restored
afterwards; full-local mode runs the whole thing with zero egress.

[demo video link] · [2-minute read: how the privacy round-trip works]

## Why this exists

Privacy LLM gateways redact chat prompts, not document piles. Cloud IDP
reconciles documents, but in the vendor's cloud, exactly what a bank, clinic
or law firm under a cloud ban cannot use. paperflow serves the gap:
cross-document reconciliation for piles that legally cannot leave the
building, running on your own AMD hardware. Built for the AMD Developer
Hackathon ACT II (Unicorn track).

## How it works

```
[architecture diagram: five agents, local/remote split marked per stage]
```

1. **Extractor** (local, **Gemma 4 31B IT** on an AMD Instinct MI300X):
   fields with provenance and confidence, straight from raw documents.
2. **Entity resolver + redactor** (local, Microsoft Presidio + custom
   recognisers): merges aliases, builds one consistent map for the whole
   pile (`Acme Corp` = `ACME Corporation` = `[ORG_1]` everywhere), redacts.
3. **Reconciler** (remote on redacted tokens via Fireworks AI, DeepSeek V4
   Pro; sensitive comparisons stay local): finds conflicts, proposes
   resolutions with rationale, escalates the rest.
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
**Full-local mode** disables remote reasoning entirely.

[screenshot: one exchange with receipt and routing chip]

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

Scored against planted ground truth in three synthetic piles
(`synthetic/*/ground_truth.json`):

| Task | Precision | Recall |
| --- | --- | --- |
| Conflict detection | [x.xx] | [x.xx] |
| Gap flagging | [x.xx] | [x.xx] |
| Alias resolution | [x.xx] | [x.xx] |
| Redaction recall | [x.xx] | [x.xx] |

Reproduce: `python eval/scorer.py --pile synthetic/kyc_onboarding`.

Extractor floor test (measured on an MI300X, 2026-07-07): 15/15 synthetic
documents, effective planted-value recovery 50/50, ~5 s per vision page.

## AMD infrastructure

All raw-sensitive work runs on a single MI300X: the entire confidential
stack (**Gemma 4 31B IT** extraction, local reconciliation, embeddings, and
the entity map) is co-resident in the 192 GB HBM3. paperflow is an
**AMD-hosted Gemma project**: Gemma does the raw-sensitive extraction and no
real identity ever leaves the card. The cloud model only ever sees redacted,
consistently-tokenised text, and in full-local mode is not used at all.

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
