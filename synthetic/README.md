# paperflow synthetic data

Three demo piles for the paperflow reconciler. Regenerate with:

    python3 generate_synthetic.py

## piles

- `kyc_onboarding/` — 4 documents (KYC form, utility bill, NRIC scan, email declaration)
- `partner_collation/` — 6 documents (registration sheets, MoU, business card, email)
- `patient_intake/` — 5 documents (intake forms, referral letter, lab requisition, insurance card)

`samples/` also contains scanned-image documents (PNG/JPEG) for the Real-pile upload demo.

## visual style

Each PDF is rendered with a company letterhead (brand mark + wordmark + coloured accent rule), a paragraph of domain-appropriate prose, the field data in a labelled block, and a legal footer. The KYC form spans two pages. Every planted VALUE stays identical across regenerations to keep the scorer's ground-truth stable.

## eval

Each pile ships a `ground_truth.json` with:

- `planted_conflicts` — same field, different value per doc; scorer checks the reconciler picks `correct`.
- `planted_gaps` — required fields missing everywhere in the pile.
- `alias_variations` — same entity, different surface form; scorer checks merge not flag.
- `sensitive_spans` — every value redaction recall must catch.

All names, IDs, addresses, phones, emails and policies are fictional.
