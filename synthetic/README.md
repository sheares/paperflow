# paperflow synthetic data

Three demo piles for the paperflow reconciler. Regenerate with:

    python3 generate_synthetic.py

## piles

- `kyc_onboarding/` — 4 PDFs (KYC forms + proof of address + NRIC scan)
- `partner_collation/` — 3 XLSX + 3 PDFs (registrations, MOU, business cards)
- `patient_intake/` — 5 PDFs (intake, referral, lab requisition, insurance card)

## eval

Each pile ships a `ground_truth.json` with:

- `planted_conflicts` — same field, different value per doc; scorer checks the reconciler picks `correct`.
- `planted_gaps` — required fields missing everywhere in the pile.
- `alias_variations` — same entity, different surface form; scorer checks merge not flag.
- `sensitive_spans` — every value redaction recall must catch.

All names, IDs, addresses, phones, emails and policies are fictional.
