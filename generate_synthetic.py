#!/usr/bin/env python3
"""
Generate synthetic paperflow demo data.

Produces PDF and Excel files for three demo piles under `synthetic/`:
- kyc_onboarding/    4 PDFs (KYC forms + proof of address + NRIC scan)
- partner_collation/ 3 XLSX + 3 PDFs (registration sheets, MOU, business cards)
- patient_intake/    5 PDFs (intake forms, referral letter, lab req, insurance card)

Each pile also gets a `ground_truth.json` for the eval harness — planted
conflicts, gaps, alias variations, and sensitive spans that reconciliation
and redaction must detect.

Install: pip install reportlab openpyxl
Run:     python3 generate_synthetic.py
"""
import json
import shutil
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment


HERE = Path(__file__).parent
OUT = HERE / 'synthetic'


# ---------- writers ------------------------------------------------------

def write_pdf(path: Path, title: str, lines):
    """Write a simple form-style PDF. `lines` items are either strings
    (rendered plain) or (label, value) tuples (rendered as a labelled row)."""
    c = canvas.Canvas(str(path), pagesize=A4)
    _, h = A4
    y = h - 28 * mm
    c.setFont('Helvetica-Bold', 13)
    c.drawString(20 * mm, y, title)
    y -= 4 * mm
    c.setStrokeColorRGB(0.7, 0.7, 0.7)
    c.line(20 * mm, y, 190 * mm, y)
    y -= 8 * mm
    for line in lines:
        if line == '':
            y -= 5 * mm
            continue
        if isinstance(line, tuple):
            label, value = line
            c.setFont('Helvetica-Bold', 10)
            c.drawString(20 * mm, y, f'{label}:' if label else '')
            c.setFont('Helvetica', 10)
            c.drawString(70 * mm, y, str(value))
        else:
            c.setFont('Helvetica', 10)
            c.drawString(20 * mm, y, str(line))
        y -= 7 * mm
    c.setFont('Helvetica-Oblique', 8)
    c.setFillColorRGB(0.55, 0.55, 0.55)
    c.drawString(20 * mm, 15 * mm, 'Synthetic document · paperflow demo · not a real record')
    c.showPage()
    c.save()


def write_txt(path: Path, lines):
    """Write a plain-text file. Items are strings or (label, value) tuples.
    Used for email-style docs (declarations, referrals, signatures) that arrive
    as plain text rather than a formatted PDF."""
    out = []
    for line in lines:
        if isinstance(line, tuple):
            label, value = line
            out.append(f'{label}: {value}' if label else str(value))
        else:
            out.append(str(line))
    path.write_text('\n'.join(out) + '\n')


def write_xlsx(path: Path, sheet_name: str, rows):
    """Write a key-value XLSX. `rows` is a list of (key, value) tuples."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    header_fill = PatternFill('solid', fgColor='EEEEEE')
    for i, (k, v) in enumerate(rows, start=1):
        key_cell = ws.cell(row=i, column=1, value=k)
        key_cell.font = Font(bold=True)
        key_cell.fill = header_fill
        ws.cell(row=i, column=2, value=v).alignment = Alignment(vertical='center')
    ws.column_dimensions['A'].width = 26
    ws.column_dimensions['B'].width = 44
    wb.save(str(path))


def write_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2))


# ---------- piles --------------------------------------------------------

def build_kyc():
    d = OUT / 'kyc_onboarding'
    d.mkdir(parents=True, exist_ok=True)

    write_pdf(d / 'kyc_form_hassan.pdf', 'Know Your Customer (KYC) Declaration Form', [
        ('Doc ID', 'doc_001'),
        ('Full Name', 'Mohammed Farid bin Hassan'),
        ('National ID (NRIC)', 'K7741209'),
        ('Residential Address', 'Blk 210 Bishan St 23 #11-04'),
        ('', 'Singapore 570210'),
        ('Beneficial Owner', 'Self'),
        ('Source of Funds', ''),
        ('Declaration Date', '2026-05-22'),
        '',
        'Signature: ______________________',
    ])

    write_pdf(d / 'utility_bill_hassan.pdf', 'SP Group · Utility Bill', [
        ('Doc ID', 'doc_002'),
        ('Account Holder', 'Farid Hassan'),
        ('Service Address', 'Blk 88 Tampines Ave 4 #05-12'),
        ('', 'Singapore 521088'),
        ('Customer Ref (NRIC)', 'K7741209'),
        ('Billing Period', '2026-04-01 to 2026-04-30'),
        ('Amount Due', 'SGD 84.30'),
    ])

    write_txt(d / 'kyc_declaration_goh.txt', [
        'From: yvonne.goh@example.com',
        'To: kyc@bank.sg',
        'Subject: KYC Declaration',
        '',
        ('Doc ID', 'doc_003'),
        '',
        'Hi team,',
        '',
        'Please find my KYC declaration below.',
        '',
        ('Full Name', 'Yvonne Goh'),
        ('National ID (NRIC)', 'K3098551'),
        ('Residential Address', '8 Marina Boulevard #30-01, Singapore 018981'),
        ('Beneficial Owner', 'Self'),
        ('Source of Funds', 'Employment income'),
        '',
        "Note: I'll pop by the branch on Monday to sign the paper form.",
        '',
        'Regards,',
        'Yvonne',
    ])

    write_pdf(d / 'nric_scan_goh.pdf', 'ID Copy (National Registration Identity Card)', [
        ('Doc ID', 'doc_004'),
        ('Name', 'Yvonne Goh'),
        ('National ID (NRIC)', 'K3098S51'),
    ])

    write_json(d / 'ground_truth.json', {
        'planted_conflicts': [
            {'field': 'Residential address', 'entity': 'Mohammed Farid bin Hassan',
             'per_doc': {'doc_001': 'Blk 210 Bishan St 23 #11-04 SG 570210',
                         'doc_002': 'Blk 88 Tampines Ave 4 #05-12 SG 521088'},
             'correct': 'Blk 210 Bishan St 23 #11-04 SG 570210'},
            {'field': 'National ID', 'entity': 'Yvonne Goh',
             'per_doc': {'doc_003': 'K3098551', 'doc_004': 'K3098S51'},
             'correct': 'K3098551', 'note': 'doc_004 OCR substituted 5 -> S'},
        ],
        'planted_gaps': [
            {'field': 'Source of funds', 'entity': 'Mohammed Farid bin Hassan',
             'reason': 'not captured on any document'},
            {'field': 'Declaration date', 'entity': 'Yvonne Goh',
             'reason': 'intake unsigned'},
        ],
        'alias_variations': [
            {'canonical': 'Mohammed Farid bin Hassan', 'aliases': ['Farid Hassan']},
        ],
        'sensitive_spans': [
            {'value': 'Mohammed Farid bin Hassan', 'type': 'PERSON'},
            {'value': 'Farid Hassan', 'type': 'PERSON'},
            {'value': 'Yvonne Goh', 'type': 'PERSON'},
            {'value': 'K7741209', 'type': 'NRIC'},
            {'value': 'K3098551', 'type': 'NRIC'},
            {'value': 'K3098S51', 'type': 'NRIC'},
            {'value': 'Blk 210 Bishan St 23 #11-04', 'type': 'ADDRESS'},
            {'value': 'Blk 88 Tampines Ave 4 #05-12', 'type': 'ADDRESS'},
            {'value': '8 Marina Boulevard #30-01', 'type': 'ADDRESS'},
            {'value': 'Singapore 570210', 'type': 'POSTCODE'},
            {'value': 'Singapore 521088', 'type': 'POSTCODE'},
            {'value': 'Singapore 018981', 'type': 'POSTCODE'},
        ],
    })


def build_partner():
    d = OUT / 'partner_collation'
    d.mkdir(parents=True, exist_ok=True)

    write_xlsx(d / 'partner_registration_acme.xlsx', 'Partner Registration', [
        ('Doc ID', 'doc_001'),
        ('Organisation', 'Acme Robotics Pte Ltd'),
        ('Contact Name', 'Lim Wei Jie'),
        ('Email', 'weijie.lim@acmerobotics.sg'),
        ('Phone', '+65 6123 4567'),
        ('UEN', '201912345A'),
        ('RSVP Status', 'Confirmed'),
    ])

    write_pdf(d / 'acme_business_card.pdf', 'Business Card', [
        ('Doc ID', 'doc_002'),
        'ACME Robotics',
        '',
        ('Contact', 'Lim Wei Jie'),
        ('Email', 'wjlim@acme.com.sg'),
        ('Phone', '+65 6123 4567'),
        '',
        'Small print: UEN 201912345A',
    ])

    write_pdf(d / 'brightpath_mou.pdf', 'Memorandum of Understanding', [
        ('Doc ID', 'doc_003'),
        ('Party', 'Brightpath Learning LLP'),
        ('UEN', 'T18LL0042K'),
        ('Primary Contact', 'Nurul Aisyah'),
        ('Executed', '2026-05-15'),
    ])

    write_xlsx(d / 'brightpath_contacts.xlsx', 'Contact Sheet', [
        ('Doc ID', 'doc_004'),
        ('Organisation', 'Brightpath Learning LLP'),
        ('Contact Name', 'Nurul Aisyah'),
        ('Email', 'aisyah@brightpath.edu.sg'),
        ('Phone', '+65 9876 5432'),
    ])

    write_xlsx(d / 'partner_registration_cobalt.xlsx', 'Partner Registration', [
        ('Doc ID', 'doc_005'),
        ('Organisation', 'Cobalt Studio'),
        ('Contact Name', 'Tan Mei Ling'),
        ('Email', 'meiling@cobaltstudio.co'),
        ('Phone', '+65 6555 2021'),
        ('UEN', '53210987B'),
        ('RSVP Status', 'Tentative'),
    ])

    write_txt(d / 'cobalt_email.txt', [
        'From: meiling@cobaltstudio.co',
        'To: partners@event.sg',
        'Sent: 2026-05-30',
        'Subject: Re: Partner event',
        '',
        ('Doc ID', 'doc_006'),
        '',
        'Hi team,',
        '',
        'Confirming my details for the event:',
        '',
        '--',
        'Cobalt Studio',
        'Tan Mei Ling',
        'meiling@cobaltstudio.co',
        '+65 6555 2020',
        '--',
        '',
        'Looking forward to it.',
        '',
        'Mei Ling',
    ])

    write_json(d / 'ground_truth.json', {
        'planted_conflicts': [
            {'field': 'Email', 'entity': 'Lim Wei Jie',
             'per_doc': {'doc_001': 'weijie.lim@acmerobotics.sg', 'doc_002': 'wjlim@acme.com.sg'},
             'correct': 'weijie.lim@acmerobotics.sg'},
            {'field': 'Phone', 'entity': 'Cobalt Studio',
             'per_doc': {'doc_005': '+65 6555 2021', 'doc_006': '+65 6555 2020'},
             'correct': '+65 6555 2020', 'note': 'doc_005 transcription typo'},
        ],
        'planted_gaps': [
            {'field': 'RSVP status', 'entity': 'Brightpath Learning LLP',
             'reason': 'not captured in either doc'},
        ],
        'alias_variations': [
            {'canonical': 'Acme Robotics Pte Ltd', 'aliases': ['ACME Robotics']},
        ],
        'sensitive_spans': [
            {'value': 'Lim Wei Jie', 'type': 'PERSON'},
            {'value': 'Nurul Aisyah', 'type': 'PERSON'},
            {'value': 'Tan Mei Ling', 'type': 'PERSON'},
            {'value': 'weijie.lim@acmerobotics.sg', 'type': 'EMAIL'},
            {'value': 'wjlim@acme.com.sg', 'type': 'EMAIL'},
            {'value': 'aisyah@brightpath.edu.sg', 'type': 'EMAIL'},
            {'value': 'meiling@cobaltstudio.co', 'type': 'EMAIL'},
            {'value': '+65 6123 4567', 'type': 'PHONE'},
            {'value': '+65 9876 5432', 'type': 'PHONE'},
            {'value': '+65 6555 2020', 'type': 'PHONE'},
            {'value': '+65 6555 2021', 'type': 'PHONE'},
            {'value': '201912345A', 'type': 'UEN'},
            {'value': 'T18LL0042K', 'type': 'UEN'},
            {'value': '53210987B', 'type': 'UEN'},
        ],
    })


def build_patient():
    d = OUT / 'patient_intake'
    d.mkdir(parents=True, exist_ok=True)

    write_pdf(d / 'intake_kumar.pdf', 'Patient Intake Form', [
        ('Doc ID', 'doc_001'),
        ('Patient Name', 'Rajesh Kumar'),
        ('Date of Birth', '1986-03-14'),
        ('NRIC / FIN', 'S8612345Z'),
        ('Policy Number', 'PRU-009281'),
        ('Allergies', 'Penicillin'),
        ('Consent Signed', ''),
        '',
        'Signature: (pending)',
    ])

    write_txt(d / 'referral_kumar.txt', [
        'From: drlee@clinicabc.sg',
        'To: cardiology@bighospital.sg',
        'Sent: 2026-06-15',
        'Subject: Referral - R. Kumar',
        '',
        ('Doc ID', 'doc_002'),
        '',
        'Dear colleague,',
        '',
        'Please see the following patient for further cardiology assessment.',
        '',
        ('Patient', 'R. Kumar'),
        ('Date of Birth', '1986-04-14'),
        ('NRIC / FIN', 'S8612345Z'),
        '',
        ('Referring Clinician', 'Dr Lee Wai Meng'),
        ('Reason', 'Further cardiology assessment'),
        '',
        'Regards,',
        'Dr Lee Wai Meng',
    ])

    write_pdf(d / 'lab_kumar.pdf', 'Lab Requisition', [
        ('Doc ID', 'doc_003'),
        ('Patient', 'Rajesh Kumar'),
        ('NRIC / FIN', 'S8612345Z'),
        ('Lab Serial', 'LABREQ-44120'),
        ('Tests Requested', 'Lipid panel, CRP, HbA1c'),
    ])

    write_pdf(d / 'intake_ng.pdf', 'Patient Intake Form', [
        ('Doc ID', 'doc_004'),
        ('Patient Name', 'Chloe Ng'),
        ('Date of Birth', '1994-11-02'),
        ('NRIC / FIN', 'S9456781D'),
        ('Policy Number', 'AIA-553102'),
        ('Allergies', ''),
        ('Consent Signed', 'Yes (2026-06-10)'),
    ])

    write_pdf(d / 'insurance_ng.pdf', 'Insurance Card', [
        ('Doc ID', 'doc_005'),
        ('Cardholder', 'Chloe Ng'),
        ('Policy Number', 'AIA-553120'),
    ])

    write_json(d / 'ground_truth.json', {
        'planted_conflicts': [
            {'field': 'Date of birth', 'entity': 'Rajesh Kumar',
             'per_doc': {'doc_001': '1986-03-14', 'doc_002': '1986-04-14'},
             'correct': '1986-03-14', 'note': 'doc_002 month transposition'},
            {'field': 'Policy number', 'entity': 'Chloe Ng',
             'per_doc': {'doc_004': 'AIA-553102', 'doc_005': 'AIA-553120'},
             'correct': 'AIA-553102', 'note': 'doc_005 final digits transposed'},
        ],
        'planted_gaps': [
            {'field': 'Consent signed', 'entity': 'Rajesh Kumar',
             'reason': 'intake unsigned'},
            {'field': 'Allergies', 'entity': 'Chloe Ng',
             'reason': 'field left blank on intake'},
        ],
        'alias_variations': [
            {'canonical': 'Rajesh Kumar', 'aliases': ['R. Kumar']},
        ],
        'sensitive_spans': [
            {'value': 'Rajesh Kumar', 'type': 'PERSON'},
            {'value': 'R. Kumar', 'type': 'PERSON'},
            {'value': 'Chloe Ng', 'type': 'PERSON'},
            {'value': 'S8612345Z', 'type': 'NRIC'},
            {'value': 'S9456781D', 'type': 'NRIC'},
            {'value': 'PRU-009281', 'type': 'POLICY'},
            {'value': 'AIA-553102', 'type': 'POLICY'},
            {'value': 'AIA-553120', 'type': 'POLICY'},
            {'value': 'LABREQ-44120', 'type': 'SERIAL'},
            {'value': '1986-03-14', 'type': 'DATE'},
            {'value': '1986-04-14', 'type': 'DATE'},
            {'value': '1994-11-02', 'type': 'DATE'},
        ],
    })


def build_readme():
    (OUT / 'README.md').write_text(
        '# paperflow synthetic data\n\n'
        'Three demo piles for the paperflow reconciler. Regenerate with:\n\n'
        '    python3 generate_synthetic.py\n\n'
        '## piles\n\n'
        '- `kyc_onboarding/` — 4 PDFs (KYC forms + proof of address + NRIC scan)\n'
        '- `partner_collation/` — 3 XLSX + 3 PDFs (registrations, MOU, business cards)\n'
        '- `patient_intake/` — 5 PDFs (intake, referral, lab requisition, insurance card)\n\n'
        '## eval\n\n'
        'Each pile ships a `ground_truth.json` with:\n\n'
        '- `planted_conflicts` — same field, different value per doc; scorer checks the reconciler picks `correct`.\n'
        '- `planted_gaps` — required fields missing everywhere in the pile.\n'
        '- `alias_variations` — same entity, different surface form; scorer checks merge not flag.\n'
        '- `sensitive_spans` — every value redaction recall must catch.\n\n'
        'All names, IDs, addresses, phones, emails and policies are fictional.\n'
    )


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    build_kyc()
    build_partner()
    build_patient()
    build_readme()
    print(f'Generated synthetic data at {OUT}/')
    for sub in sorted(OUT.iterdir()):
        if sub.is_dir():
            files = sorted(sub.iterdir())
            print(f'  {sub.name}/  ({len(files)} files)')
            for f in files:
                print(f'    {f.name}')


if __name__ == '__main__':
    main()
