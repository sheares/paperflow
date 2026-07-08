#!/usr/bin/env python3
"""
Generate synthetic paperflow demo data.

Three demo piles produced under `synthetic/`:
- kyc_onboarding/    KYC forms, proof of address, NRIC scan, email declaration
- partner_collation/ Registration sheets, MoU, business cards, email footers
- patient_intake/    Intake forms, referral letters, lab requisition, insurance

Every PDF ships with a real-looking company letterhead (typography, a
small geometric brand mark, a coloured accent rule), a paragraph of
domain-appropriate prose, the field data in a labelled block, and a
legal footer. The KYC form is multi-page. Every planted VALUE stays
identical to keep the scorer's ground-truth stable across regenerations.

`synthetic/samples/` also contains a small set of scanned-image
documents (PNG/JPEG) for the Real-pile upload demo, so judges can see
Gemma extract fields from actual bitmap docs.

Install: pip install reportlab openpyxl pillow
Run:     python3 generate_synthetic.py
"""
import json
import random
import shutil
import textwrap
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font as XLFont, PatternFill, Side
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


HERE = Path(__file__).parent
OUT = HERE / 'synthetic'

# ---- palette ------------------------------------------------------------
INK = HexColor('#131313')
INK_SOFT = HexColor('#2A2A2A')
MUTED = HexColor('#585858')
FAINT = HexColor('#8A8A8A')
HAIR = HexColor('#DCDCDC')
BG_SOFT = HexColor('#F6F7F9')


# ---- reusable pdf primitives -------------------------------------------

def _wordmark(c, x, y, text, brand, size=15):
    """Draw a small square mark + wordmark. The mark is two overlapping
    shapes so it reads as a real brand element without being a logo."""
    c.setFillColor(brand)
    # square with a subtle notch
    c.rect(x, y - 4, 7 * mm, 7 * mm, fill=1, stroke=0)
    c.setFillColor(HexColor('#FFFFFF'))
    c.circle(x + 4.8 * mm, y - 0.5 * mm, 1.6 * mm, fill=1, stroke=0)
    c.setFillColor(brand)
    c.setFont('Helvetica-Bold', size)
    c.drawString(x + 10 * mm, y, text)


def _accent_bar(c, x, y, w, brand, thick=1.4):
    c.setStrokeColor(brand)
    c.setLineWidth(thick)
    c.line(x, y, x + w, y)


def _header(c, company, tagline, brand, address=None, contact=None):
    """Full letterhead: mark + wordmark, tagline, meta on the right, rule."""
    _, h = A4
    y = h - 20 * mm
    _wordmark(c, 20 * mm, y, company, brand)
    if address or contact:
        c.setFillColor(MUTED); c.setFont('Helvetica', 8)
        if address:
            c.drawRightString(190 * mm, y + 1 * mm, address)
        if contact:
            c.drawRightString(190 * mm, y - 3 * mm, contact)
    c.setFillColor(MUTED); c.setFont('Helvetica', 9)
    c.drawString(30 * mm, y - 5.5 * mm, tagline)
    _accent_bar(c, 20 * mm, y - 10 * mm, 170 * mm, brand)
    return y - 16 * mm


def _title_block(c, x, y, title, sub=None):
    c.setFillColor(INK); c.setFont('Helvetica-Bold', 13)
    c.drawString(x, y, title)
    y -= 5 * mm
    if sub:
        c.setFillColor(MUTED); c.setFont('Helvetica', 9)
        c.drawString(x, y, sub)
        y -= 4 * mm
    return y - 4 * mm


def _prose(c, x, y, text, width_chars=95, size=9.5, leading=4.6 * mm,
           font='Helvetica', colour=INK_SOFT):
    c.setFillColor(colour); c.setFont(font, size)
    for para in text.split('\n\n'):
        for line in textwrap.wrap(para.strip(), width=width_chars):
            c.drawString(x, y, line)
            y -= leading
        y -= leading * 0.4
    return y


def _fields(c, x, y, rows, label_w=55 * mm, gap=6.5 * mm):
    """Render (label, value) pairs. Labels carry a colon so pdftotext -layout
    preserves the label-value structure that the redactor's scan uses."""
    for row in rows:
        if row == '':
            y -= gap * 0.6
            continue
        if isinstance(row, tuple):
            label, value = row
            if label:
                c.setFillColor(MUTED); c.setFont('Helvetica-Bold', 9)
                c.drawString(x, y, f'{label}:')
            c.setFillColor(INK); c.setFont('Helvetica', 10.5)
            c.drawString(x + label_w, y, str(value))
        else:
            c.setFillColor(INK); c.setFont('Helvetica', 10)
            c.drawString(x, y, str(row))
        y -= gap
    return y


def _card_box(c, x, y, w, h, brand):
    """A subtle box that groups a labelled data table."""
    c.setStrokeColor(HAIR); c.setLineWidth(0.6)
    c.setFillColor(BG_SOFT)
    c.roundRect(x, y - h, w, h, 3 * mm, fill=1, stroke=1)
    c.setFillColor(brand)
    c.rect(x, y - 2 * mm, 3 * mm, 2 * mm, fill=1, stroke=0)


def _sig_block(c, x, y, sig_hint='______________________________'):
    c.setFillColor(MUTED); c.setFont('Helvetica', 9)
    c.drawString(x, y, 'Signature:')
    c.setFillColor(INK); c.setFont('Helvetica', 10.5)
    c.drawString(x + 25 * mm, y, sig_hint)
    y -= 7 * mm
    c.setFillColor(MUTED); c.setFont('Helvetica', 9)
    c.drawString(x, y, 'Date:')
    c.setFillColor(INK); c.setFont('Helvetica', 10.5)
    c.drawString(x + 25 * mm, y, '___________________')
    return y - 8 * mm


def _footer(c, lines):
    c.setFillColor(FAINT); c.setFont('Helvetica', 7.2)
    y = 15 * mm
    for line in lines:
        c.drawString(20 * mm, y, line)
        y -= 3 * mm


def _watermark(c):
    c.setFillColor(FAINT); c.setFont('Helvetica-Oblique', 7)
    c.drawString(20 * mm, 8 * mm,
                 'Synthetic document · paperflow demo · not a real record')


def _page_num(c, page, of):
    c.setFillColor(MUTED); c.setFont('Helvetica', 8)
    c.drawRightString(190 * mm, 8 * mm, f'Page {page} of {of}')


# ---- txt / xlsx / json --------------------------------------------------

def write_txt(path: Path, lines):
    out = []
    for line in lines:
        if isinstance(line, tuple):
            label, value = line
            out.append(f'{label}: {value}' if label else str(value))
        else:
            out.append(str(line))
    path.write_text('\n'.join(out) + '\n')


def write_xlsx(path: Path, sheet_name: str, rows, extra_rows=None,
               title=None, subtitle=None, note=None,
               title_bg='1F3B73'):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    thin = Side(border_style='thin', color='CCCCCC')
    header_fill = PatternFill('solid', fgColor='F0F2F5')
    title_fill = PatternFill('solid', fgColor=title_bg)

    r = 1
    if title:
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
        cell = ws.cell(row=r, column=1, value=title)
        cell.font = XLFont(bold=True, color='FFFFFF', size=13)
        cell.fill = title_fill
        cell.alignment = Alignment(horizontal='left', vertical='center', indent=1)
        ws.row_dimensions[r].height = 26
        r += 1
    if subtitle:
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
        cell = ws.cell(row=r, column=1, value=subtitle)
        cell.font = XLFont(italic=True, color='585858', size=9)
        cell.alignment = Alignment(horizontal='left', vertical='center', indent=1)
        r += 1
    r += 1
    for k, v in rows:
        key_cell = ws.cell(row=r, column=1, value=k)
        key_cell.font = XLFont(bold=True)
        key_cell.fill = header_fill
        key_cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
        val_cell = ws.cell(row=r, column=2, value=v)
        val_cell.alignment = Alignment(vertical='center')
        val_cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
        ws.row_dimensions[r].height = 20
        r += 1
    if extra_rows:
        r += 1
        for k, v in extra_rows:
            ws.cell(row=r, column=1, value=k).font = XLFont(italic=True, color='585858')
            ws.cell(row=r, column=2, value=v).font = XLFont(color='585858')
            r += 1
    if note:
        r += 1
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
        cell = ws.cell(row=r, column=1, value=note)
        cell.font = XLFont(italic=True, color='8A8A8A', size=9)

    ws.column_dimensions['A'].width = 30
    ws.column_dimensions['B'].width = 54
    wb.save(str(path))


def write_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2))


# ---- image (bitmap) documents -------------------------------------------

def _load_font(pref_list, size):
    for name in pref_list:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


BODY_FONT_CANDIDATES = [
    '/System/Library/Fonts/Supplemental/Arial.ttf',
    '/System/Library/Fonts/Helvetica.ttc',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
]
BOLD_FONT_CANDIDATES = [
    '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
    '/Library/Fonts/Arial Bold.ttf',
    '/System/Library/Fonts/Helvetica.ttc',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
]


def _paper_texture(img: Image.Image):
    """Add subtle noise so the image reads as a scan, not a screenshot."""
    r = random.Random(42)
    px = img.load()
    w, h = img.size
    for _ in range(w * h // 32):
        x, y = r.randrange(w), r.randrange(h)
        v = r.randint(-10, 4)
        p = px[x, y]
        px[x, y] = tuple(max(0, min(255, c + v)) for c in p[:3])
    return img.filter(ImageFilter.GaussianBlur(0.3))


def _render_scan_jpeg(path: Path, title: str, rows: list[tuple[str, str]],
                      brand=(210, 25, 30), rotate=1.2,
                      size=(1200, 1650)):
    """Render a form as a landscape/portrait JPEG that reads as a
    photographed/scanned paper document. `rows` is (label, value)."""
    img = Image.new('RGB', size, (252, 250, 246))
    draw = ImageDraw.Draw(img)
    w, h = size

    title_font = _load_font(BOLD_FONT_CANDIDATES, 44)
    tag_font = _load_font(BODY_FONT_CANDIDATES, 18)
    lbl_font = _load_font(BOLD_FONT_CANDIDATES, 22)
    val_font = _load_font(BODY_FONT_CANDIDATES, 24)
    small_font = _load_font(BODY_FONT_CANDIDATES, 14)

    # brand mark
    draw.rectangle([80, 80, 130, 130], fill=brand)
    draw.ellipse([100, 95, 122, 117], fill=(255, 255, 255))
    draw.text((150, 80), title.split('·')[0].strip(),
              font=title_font, fill=(20, 20, 20))
    draw.text((150, 140), title.split('·', 1)[1].strip() if '·' in title
              else '', font=tag_font, fill=(90, 90, 90))
    draw.line([(80, 180), (w - 80, 180)], fill=brand, width=3)

    y = 240
    for row in rows:
        if row == '':
            y += 20; continue
        if isinstance(row, tuple):
            label, value = row
            if label:
                draw.text((80, y), f'{label}:', font=lbl_font, fill=(70, 70, 70))
            draw.text((400, y), str(value), font=val_font, fill=(15, 15, 15))
        else:
            draw.text((80, y), str(row), font=val_font, fill=(15, 15, 15))
        y += 55

    # rubber stamp
    y_stamp = h - 380
    r = random.Random(hash(path.name) & 0xFFFF)
    sx, sy = w - 320 + r.randint(-10, 10), y_stamp + r.randint(-5, 5)
    for offset in range(3):
        draw.ellipse(
            [sx + offset, sy + offset, sx + 220 - offset, sy + 160 - offset],
            outline=(120, 20, 20), width=3)
    draw.text((sx + 34, sy + 40), 'RECEIVED', font=lbl_font,
              fill=(120, 20, 20))
    draw.text((sx + 44, sy + 90), 'FILE COPY', font=small_font,
              fill=(120, 20, 20))

    # footer
    draw.line([(80, h - 130), (w - 80, h - 130)], fill=(200, 200, 200), width=1)
    draw.text((80, h - 100), 'Synthetic document · paperflow demo · not a real record',
              font=small_font, fill=(140, 140, 140))

    img = _paper_texture(img)
    if rotate:
        img = img.rotate(rotate, resample=Image.BICUBIC, fillcolor=(252, 250, 246), expand=False)
    img.save(path, 'JPEG', quality=88)


def _render_id_card_png(path: Path, name: str, nric: str,
                        dob: str = '02 Nov 1994', size=(1000, 620)):
    """Render a Singapore-NRIC-shaped photo/scan as PNG."""
    img = Image.new('RGB', size, (215, 220, 210))
    draw = ImageDraw.Draw(img)
    w, h = size

    # card body
    card = Image.new('RGB', (860, 500), (238, 232, 214))
    cdraw = ImageDraw.Draw(card)
    # header band
    cdraw.rectangle([0, 0, 860, 90], fill=(170, 25, 25))
    header_font = _load_font(BOLD_FONT_CANDIDATES, 26)
    sub_font = _load_font(BODY_FONT_CANDIDATES, 16)
    lbl_font = _load_font(BOLD_FONT_CANDIDATES, 18)
    val_font = _load_font(BODY_FONT_CANDIDATES, 22)
    cdraw.text((30, 22), 'REPUBLIC OF SINGAPORE',
               font=header_font, fill=(255, 255, 255))
    cdraw.text((30, 55),
               'NATIONAL REGISTRATION IDENTITY CARD',
               font=sub_font, fill=(255, 240, 240))

    # portrait placeholder (silhouette)
    cdraw.rectangle([30, 120, 240, 380], fill=(180, 175, 165))
    cdraw.ellipse([80, 155, 190, 265], fill=(140, 135, 125))
    cdraw.rectangle([70, 275, 200, 380], fill=(150, 145, 135))

    # data
    cdraw.text((280, 130), 'Name', font=lbl_font, fill=(80, 60, 60))
    cdraw.text((280, 158), name, font=val_font, fill=(30, 25, 20))
    cdraw.text((280, 220), 'NRIC No.', font=lbl_font, fill=(80, 60, 60))
    cdraw.text((280, 248), nric, font=val_font, fill=(30, 25, 20))
    cdraw.text((280, 310), 'Date of Birth', font=lbl_font, fill=(80, 60, 60))
    cdraw.text((280, 338), dob, font=val_font, fill=(30, 25, 20))

    # signature squiggle
    cdraw.line([(280, 420), (300, 415), (330, 430), (360, 410),
                (400, 425), (440, 415)], fill=(30, 20, 20), width=2)

    # paste card slightly rotated
    card = card.rotate(-1.2, resample=Image.BICUBIC, expand=True,
                       fillcolor=(215, 220, 210))
    px = (w - card.width) // 2
    py = (h - card.height) // 2
    img.paste(card, (px, py))
    # camera-ish vignette
    for i in range(80):
        alpha = int(80 * (1 - i / 80))
        img.putalpha(255)
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.rectangle([i, i, w - i, h - i], outline=(0, 0, 0, alpha // 8))
        img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')

    img = _paper_texture(img)
    img.save(path, 'PNG')


def _render_signed_letter_jpeg(path: Path, header: str, tagline: str,
                               brand, body_paragraphs, sign_off_name,
                               sign_off_title, size=(1240, 1650)):
    """A prose letter that has been printed, signed, and scanned."""
    img = Image.new('RGB', size, (250, 249, 244))
    draw = ImageDraw.Draw(img)
    w, h = size

    title_font = _load_font(BOLD_FONT_CANDIDATES, 34)
    tag_font = _load_font(BODY_FONT_CANDIDATES, 16)
    body_font = _load_font(BODY_FONT_CANDIDATES, 22)
    sig_name_font = _load_font(BOLD_FONT_CANDIDATES, 24)
    small_font = _load_font(BODY_FONT_CANDIDATES, 14)

    # brand mark + wordmark
    draw.rectangle([90, 90, 140, 140], fill=brand)
    draw.polygon([(100, 100), (130, 100), (115, 130)], fill=(255, 255, 255))
    draw.text((160, 90), header, font=title_font, fill=(20, 20, 20))
    draw.text((160, 140), tagline, font=tag_font, fill=(90, 90, 90))
    draw.line([(90, 175), (w - 90, 175)], fill=brand, width=3)

    y = 240
    for para in body_paragraphs:
        for line in textwrap.wrap(para, width=72):
            draw.text((90, y), line, font=body_font, fill=(30, 30, 30))
            y += 32
        y += 18

    # signature (handwritten squiggle)
    y += 20
    draw.text((90, y), 'Yours sincerely,',
              font=body_font, fill=(30, 30, 30))
    y += 40
    r = random.Random(hash(sign_off_name) & 0xFFFF)
    xs = 90
    for i in range(6):
        draw.line([(xs + i * 22 + r.randint(-4, 4),
                    y + r.randint(-4, 8)),
                   (xs + (i + 1) * 22 + r.randint(-4, 4),
                    y + r.randint(-12, 6))],
                  fill=(20, 25, 60), width=3)
    y += 40
    draw.text((90, y), sign_off_name, font=sig_name_font, fill=(20, 20, 20))
    y += 32
    draw.text((90, y), sign_off_title, font=tag_font, fill=(90, 90, 90))

    draw.line([(90, h - 130), (w - 90, h - 130)],
              fill=(200, 200, 200), width=1)
    draw.text((90, h - 100),
              'Synthetic document · paperflow demo · not a real record',
              font=small_font, fill=(140, 140, 140))

    img = _paper_texture(img).rotate(0.4, resample=Image.BICUBIC,
                                     fillcolor=(250, 249, 244), expand=False)
    img.save(path, 'JPEG', quality=90)


# ---- KYC pile -----------------------------------------------------------

DBS_BRAND = HexColor('#E11B22')
SP_BRAND = HexColor('#00A9CE')
NRIC_BRAND = HexColor('#B01818')
HEART_BRAND = HexColor('#0072CE')
AIA_BRAND = HexColor('#D71920')
INNO_BRAND = HexColor('#6A1B9A')
ACME_BRAND = HexColor('#0B3D91')
BRIGHT_BRAND = HexColor('#2E7D32')
COBALT_BRAND = HexColor('#1F3B73')


def build_kyc():
    d = OUT / 'kyc_onboarding'
    d.mkdir(parents=True, exist_ok=True)

    # ---- 1. Multi-page KYC declaration (DBS)
    c = canvas.Canvas(str(d / 'kyc_form_hassan.pdf'), pagesize=A4)

    # PAGE 1
    y = _header(c, 'DBS Private', 'Wealth Onboarding · KYC/AML Documentation',
                DBS_BRAND,
                address='12 Marina Boulevard, Singapore 018982',
                contact='Tel +65 6878 8888  ·  dbs.com.sg/private')
    y = _title_block(c, 20 * mm, y,
                     'Know Your Customer (KYC) Declaration Form',
                     'Reference: KYC/2026/05/00218   ·   Series 2026-B')
    y = _prose(c, 20 * mm, y,
               "I, the undersigned, declare that the information provided in "
               "this form is true, complete and accurate to the best of my "
               "knowledge. I understand that this declaration forms the basis "
               "of the Bank's assessment under the Monetary Authority of "
               "Singapore's Notice 626 (AML/CFT), and that any material "
               "misrepresentation may result in the account being suspended, "
               "the banking relationship being terminated, and referral to "
               "the Suspicious Transaction Reporting Office.")
    y -= 2 * mm
    c.setFillColor(INK); c.setFont('Helvetica-Bold', 11)
    c.drawString(20 * mm, y, 'Section A · Applicant details')
    y -= 6 * mm
    y = _fields(c, 20 * mm, y, [
        ('Doc ID', 'doc_001'),
        ('Full Name', 'Mohammed Farid bin Hassan'),
        ('National ID (NRIC)', 'K7741209'),
        ('Residential Address', 'Blk 210 Bishan St 23 #11-04'),
        ('', 'Singapore 570210'),
        ('Beneficial Owner', 'Self'),
        ('Source of Funds', ''),
        ('Declaration Date', '2026-05-22'),
    ])
    y -= 2 * mm
    y = _prose(c, 20 * mm, y,
               "I acknowledge that the Bank may request supplementary "
               "documentation to verify any statement above, and I consent "
               "to such requests being made in writing to the address on "
               "record.")
    _footer(c, [
        'DBS Bank Ltd  ·  UEN 196800306E  ·  Registered office: 12 Marina Boulevard, DBS Asia Central Tower 3, Singapore 018982',
        'This form is confidential and intended solely for the named applicant and DBS Wealth Onboarding.',
    ])
    _watermark(c); _page_num(c, 1, 2); c.showPage()

    # PAGE 2 (declarations + signature)
    y = _header(c, 'DBS Private', 'Wealth Onboarding · KYC/AML Documentation',
                DBS_BRAND,
                address='12 Marina Boulevard, Singapore 018982',
                contact='Tel +65 6878 8888  ·  dbs.com.sg/private')
    y = _title_block(c, 20 * mm, y, 'Section B · Declarations & signature',
                     'Reference: KYC/2026/05/00218   ·   continued')
    y = _prose(c, 20 * mm, y,
               "1. I confirm that I am not a Politically Exposed Person and "
               "that no member of my immediate family holds a public office "
               "or a senior position in a foreign government.\n\n"
               "2. I confirm that the funds referenced in Section A are "
               "derived from lawful sources.\n\n"
               "3. I consent to the Bank sharing my information with its "
               "authorised affiliates for the sole purpose of onboarding "
               "and ongoing due diligence.\n\n"
               "4. I understand that this declaration remains valid until "
               "superseded by a fresh declaration executed by me.")
    y -= 4 * mm
    _sig_block(c, 20 * mm, y)
    _footer(c, [
        'DBS Bank Ltd  ·  UEN 196800306E  ·  Registered office: 12 Marina Boulevard, DBS Asia Central Tower 3, Singapore 018982',
        'Personal data collected on this form is handled in accordance with the DBS Group Privacy Policy.',
    ])
    _watermark(c); _page_num(c, 2, 2); c.save()

    # ---- 2. Utility bill (SP Group)
    c = canvas.Canvas(str(d / 'utility_bill_hassan.pdf'), pagesize=A4)
    y = _header(c, 'SP Group', 'Electricity, water and gas utilities',
                SP_BRAND,
                address='2 Kallang Sector, Singapore 349277',
                contact='Tel 1800 222 2333  ·  spgroup.com.sg')
    y = _title_block(c, 20 * mm, y, 'Utility Bill',
                     'Statement Date 2026-05-02   ·   Account No. 03-124-5502-1')
    y = _prose(c, 20 * mm, y,
               "Dear customer, thank you for continuing your service with "
               "SP Group. Your April 2026 statement is below. Total "
               "household consumption for this billing period was 314 kWh, "
               "in line with the seasonal average for a 4-room HDB flat.")
    y -= 2 * mm
    y = _fields(c, 20 * mm, y, [
        ('Doc ID', 'doc_002'),
        ('Account Holder', 'Farid Hassan'),
        ('Service Address', 'Blk 88 Tampines Ave 4 #05-12'),
        ('', 'Singapore 521088'),
        ('Customer Ref (NRIC)', 'K7741209'),
        ('Billing Period', '2026-04-01 to 2026-04-30'),
        ('Amount Due', 'SGD 84.30'),
    ])
    y -= 4 * mm
    y = _prose(c, 20 * mm, y,
               "Payment is due by 2026-05-22. You may pay via AXS, GIRO, "
               "PayNow to UEN 199504676R, or at any SingPost branch. For "
               "assistance with billing queries, please quote your "
               "account number when calling the customer care line.")
    _footer(c, [
        'SP Services Ltd  ·  UEN 199504676R  ·  2 Kallang Sector, Singapore 349277',
        'Late payments attract a reconnection fee of SGD 12.60. Please retain this statement for your records.',
    ])
    _watermark(c); c.save()

    # ---- 3. Yvonne's email declaration (txt)
    write_txt(d / 'kyc_declaration_goh.txt', [
        'From: yvonne.goh@example.com',
        'To: kyc@bank.sg',
        'Subject: KYC Declaration',
        'Date: 2026-05-24 14:12 SGT',
        '',
        ('Doc ID', 'doc_003'),
        '',
        'Hi team,',
        '',
        'Please find my KYC declaration below. I have reviewed the form and',
        'confirm the following details are accurate as at today. I will also',
        'attach a scan of my NRIC in a separate message so the two documents',
        'do not exceed the mailbox size cap.',
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
        'Yvonne Goh',
        'Senior Product Manager, Fintech Practice',
        '8 Marina Boulevard #30-01, Singapore 018981',
    ])

    # ---- 4. NRIC scan (PDF wrapper of what a photocopy looks like)
    c = canvas.Canvas(str(d / 'nric_scan_goh.pdf'), pagesize=A4)
    y = _header(c, 'REPUBLIC OF SINGAPORE',
                'National Registration Identity Card · Immigration & Checkpoints Authority',
                NRIC_BRAND, contact='ICA · Singapore')
    y = _title_block(c, 20 * mm, y, 'ID Copy (Photostat)',
                     "Scan submitted with Yvonne Goh's KYC declaration email.")
    y = _prose(c, 20 * mm, y,
               "The following details were transcribed from the National "
               "Registration Identity Card scan below. Small print on the "
               "physical card is often difficult to read cleanly; any "
               "discrepancy against the KYC declaration should be flagged.")
    y -= 4 * mm
    _card_box(c, 20 * mm, y, 170 * mm, 40 * mm, NRIC_BRAND)
    y = _fields(c, 25 * mm, y - 5 * mm, [
        ('Doc ID', 'doc_004'),
        ('Name', 'Yvonne Goh'),
        ('National ID (NRIC)', 'K3098S51'),
        ('Date of Issue', '2018-11-22'),
    ])
    _footer(c, [
        'This is a photocopy for verification purposes only.  Original document remains with the cardholder.',
    ])
    _watermark(c); c.save()

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


# ---- Partner pile -------------------------------------------------------

def build_partner():
    d = OUT / 'partner_collation'
    d.mkdir(parents=True, exist_ok=True)

    write_xlsx(d / 'partner_registration_acme.xlsx', 'Partner Registration',
               title='PartnerConnect · Vendor Registration',
               subtitle='Registration Portal partners.event.sg  ·  Series 2026-B',
               title_bg='0B3D91',
               rows=[
                   ('Doc ID', 'doc_001'),
                   ('Organisation', 'Acme Robotics Pte Ltd'),
                   ('Contact Name', 'Lim Wei Jie'),
                   ('Email', 'weijie.lim@acmerobotics.sg'),
                   ('Phone', '+65 6123 4567'),
                   ('UEN', '201912345A'),
                   ('RSVP Status', 'Confirmed'),
               ],
               extra_rows=[
                   ('Submitted', '2026-05-14 09:41 SGT'),
                   ('Reviewed by', 'partners@event.sg'),
               ],
               note='This form was submitted via the PartnerConnect portal. Please raise any corrections through the vendor helpdesk.')

    # ---- ACME business card
    c = canvas.Canvas(str(d / 'acme_business_card.pdf'), pagesize=A4)
    y = _header(c, 'ACME Robotics',
                'Industrial automation and integration services',
                ACME_BRAND,
                address='12 Tuas Bay Walk, Singapore 638743',
                contact='Tel +65 6789 1121  ·  acmerobotics.sg')
    y = _title_block(c, 20 * mm, y, 'Business Card (Scanned)',
                     'Received at the SME connect networking session, 2026-05-10.')
    y = _prose(c, 20 * mm, y,
               "The following contact details were transcribed from a "
               "business card exchanged during the SME connect networking "
               "session. Please note that the small print on the reverse "
               "of the card lists a different administrative email; both "
               "should be treated as valid contact points.")
    y -= 2 * mm
    y = _fields(c, 20 * mm, y, [
        ('Doc ID', 'doc_002'),
        ('Organisation', 'ACME Robotics'),
        ('Contact', 'Lim Wei Jie'),
        ('Role', 'Head of Business Development'),
        ('Email', 'wjlim@acme.com.sg'),
        ('Phone', '+65 6123 4567'),
        ('Direct Line', '+65 6789 1121'),
    ])
    y -= 2 * mm
    c.setFillColor(FAINT); c.setFont('Helvetica-Oblique', 8)
    c.drawString(20 * mm, y, 'Small print: UEN 201912345A  ·  ACRA-registered since 2019')
    _footer(c, ['ACME Robotics Pte Ltd  ·  12 Tuas Bay Walk, Singapore 638743'])
    _watermark(c); c.save()

    # ---- MoU
    c = canvas.Canvas(str(d / 'brightpath_mou.pdf'), pagesize=A4)
    y = _header(c, 'Brightpath Learning',
                'MoE approved enrichment provider',
                BRIGHT_BRAND,
                address='15 Beach Road #04-08, Singapore 189677',
                contact='Tel +65 9876 5432  ·  brightpath.edu.sg')
    y = _title_block(c, 20 * mm, y, 'Memorandum of Understanding',
                     'Community Partnership Programme  ·  Series 2026-B')
    y = _prose(c, 20 * mm, y,
               "This Memorandum of Understanding is entered into on the "
               "date shown below between the parties named. It sets out "
               "the cooperative arrangements for the delivery of "
               "after-school enrichment programmes across three "
               "participating community centres during the second half of "
               "2026.")
    y -= 2 * mm
    y = _fields(c, 20 * mm, y, [
        ('Doc ID', 'doc_003'),
        ('Party', 'Brightpath Learning LLP'),
        ('UEN', 'T18LL0042K'),
        ('Primary Contact', 'Nurul Aisyah'),
        ('Executed', '2026-05-15'),
    ])
    y -= 2 * mm
    y = _prose(c, 20 * mm, y,
               "1. Term. This MoU takes effect on the date of execution "
               "and expires on 31 December 2026, unless extended in "
               "writing.\n\n"
               "2. Responsibilities. Brightpath shall provide qualified "
               "facilitators, all curriculum materials, and public "
               "liability insurance covering registered participants.\n\n"
               "3. Confidentiality. Each party shall treat the personal "
               "data of participants disclosed under this MoU in "
               "accordance with the Personal Data Protection Act 2012.")
    _sig_block(c, 20 * mm, y)
    _footer(c, [
        'Brightpath Learning LLP  ·  UEN T18LL0042K  ·  15 Beach Road #04-08, Singapore 189677',
    ])
    _watermark(c); c.save()

    write_xlsx(d / 'brightpath_contacts.xlsx', 'Contact Sheet',
               title='Brightpath Learning · Primary Contact',
               subtitle='Extracted from internal partner directory · last verified 2026-05-30',
               title_bg='2E7D32',
               rows=[
                   ('Doc ID', 'doc_004'),
                   ('Organisation', 'Brightpath Learning LLP'),
                   ('Contact Name', 'Nurul Aisyah'),
                   ('Email', 'aisyah@brightpath.edu.sg'),
                   ('Phone', '+65 9876 5432'),
               ],
               extra_rows=[
                   ('Role', 'Programmes Lead'),
                   ('Preferred Hours', 'Weekdays 9am - 6pm'),
               ])

    write_xlsx(d / 'partner_registration_cobalt.xlsx', 'Partner Registration',
               title='PartnerConnect · Vendor Registration',
               subtitle='Registration Portal partners.event.sg  ·  Series 2026-B',
               title_bg='0B3D91',
               rows=[
                   ('Doc ID', 'doc_005'),
                   ('Organisation', 'Cobalt Studio'),
                   ('Contact Name', 'Tan Mei Ling'),
                   ('Email', 'meiling@cobaltstudio.co'),
                   ('Phone', '+65 6555 2021'),
                   ('UEN', '53210987B'),
                   ('RSVP Status', 'Tentative'),
               ],
               extra_rows=[
                   ('Submitted', '2026-05-14 15:20 SGT'),
                   ('Reviewed by', 'partners@event.sg'),
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
        "Thanks for the follow-up. Confirming my details for the event as",
        'below. The phone number on the registration form was the office',
        "line, but the mobile below is the fastest way to reach me on the",
        'day.',
        '',
        '--',
        'Cobalt Studio',
        'Tan Mei Ling  ·  Creative Director',
        'meiling@cobaltstudio.co',
        '+65 6555 2020',
        '25A Cantonment Road #03-01, Singapore 089745',
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


# ---- Patient pile -------------------------------------------------------

def build_patient():
    d = OUT / 'patient_intake'
    d.mkdir(parents=True, exist_ok=True)

    # Intake (Rajesh)
    c = canvas.Canvas(str(d / 'intake_kumar.pdf'), pagesize=A4)
    y = _header(c, 'National Heart Centre',
                'Outpatient Cardiology · MoH-accredited',
                HEART_BRAND,
                address='5 Hospital Drive, Singapore 169609',
                contact='Tel +65 6704 8000  ·  nhcs.com.sg')
    y = _title_block(c, 20 * mm, y, 'Patient Intake Form',
                     'Referral received 2026-06-15  ·  Clinic Cardiology Outpatient · Room B/2')
    y = _prose(c, 20 * mm, y,
               "This form captures the details submitted by the patient at "
               "the point of registration. All fields marked as required "
               "under the Ministry of Health National Standards for "
               "Medical Records must be completed before consultation.")
    y = _fields(c, 20 * mm, y, [
        ('Doc ID', 'doc_001'),
        ('Patient Name', 'Rajesh Kumar'),
        ('Date of Birth', '1986-03-14'),
        ('NRIC / FIN', 'S8612345Z'),
        ('Policy Number', 'PRU-009281'),
        ('Allergies', 'Penicillin'),
        ('Consent Signed', ''),
    ])
    y -= 4 * mm
    _sig_block(c, 20 * mm, y, sig_hint='(pending)')
    _footer(c, [
        'National Heart Centre Singapore Pte Ltd  ·  Company Reg No. 199801148C',
        'This form is a medical record. Unauthorised disclosure is an offence under the Personal Data Protection Act 2012.',
    ])
    _watermark(c); c.save()

    # Referral letter (txt)
    write_txt(d / 'referral_kumar.txt', [
        'From: drlee@clinicabc.sg',
        'To: cardiology@bighospital.sg',
        'Sent: 2026-06-15 10:32 SGT',
        'Subject: Referral - R. Kumar',
        '',
        ('Doc ID', 'doc_002'),
        '',
        'Dear colleague,',
        '',
        'Please see the following patient for further cardiology assessment.',
        'He has been on my books for eighteen months for hypertension. At',
        "his recent review, his ECG showed occasional T-wave inversions in",
        'the lateral leads that I would like a specialist opinion on.',
        '',
        ('Patient', 'R. Kumar'),
        ('Date of Birth', '1986-04-14'),
        ('NRIC / FIN', 'S8612345Z'),
        '',
        ('Referring Clinician', 'Dr Lee Wai Meng'),
        ('Reason', 'Further cardiology assessment'),
        '',
        'I am attaching his most recent lab requisition and ECG report',
        'separately for your reference.',
        '',
        'Regards,',
        'Dr Lee Wai Meng, MBBS (Sing), FRACGP',
        'Clinic ABC, 218 East Coast Road #02-33, Singapore 428917',
    ])

    # Lab requisition
    c = canvas.Canvas(str(d / 'lab_kumar.pdf'), pagesize=A4)
    y = _header(c, 'Innoquest Diagnostics',
                'Clinical laboratory services',
                INNO_BRAND,
                address='63 Hillview Avenue #06-16, Singapore 669569',
                contact='Tel +65 6580 8600  ·  innoquest.sg')
    y = _title_block(c, 20 * mm, y, 'Lab Requisition',
                     'Requesting Clinician: Dr Lee Wai Meng · Clinic ABC')
    y = _prose(c, 20 * mm, y,
               "The following tests have been requested for the patient "
               "named below in support of an ongoing cardiology "
               "assessment. Samples should be drawn fasting where "
               "indicated, and results routed to the referring clinician.")
    y = _fields(c, 20 * mm, y, [
        ('Doc ID', 'doc_003'),
        ('Patient', 'Rajesh Kumar'),
        ('NRIC / FIN', 'S8612345Z'),
        ('Lab Serial', 'LABREQ-44120'),
        ('Tests Requested', 'Lipid panel, CRP, HbA1c'),
    ])
    _footer(c, [
        'Innoquest Diagnostics Pte Ltd  ·  63 Hillview Avenue #06-16, Singapore 669569',
        'Please phone 6580 8600 for urgent requisitions or specimen collection support.',
    ])
    _watermark(c); c.save()

    # Intake (Chloe)
    c = canvas.Canvas(str(d / 'intake_ng.pdf'), pagesize=A4)
    y = _header(c, 'National Heart Centre',
                'Outpatient Cardiology · MoH-accredited',
                HEART_BRAND,
                address='5 Hospital Drive, Singapore 169609',
                contact='Tel +65 6704 8000  ·  nhcs.com.sg')
    y = _title_block(c, 20 * mm, y, 'Patient Intake Form',
                     'Referral received 2026-06-10  ·  Clinic Cardiology Outpatient · Room B/2')
    y = _prose(c, 20 * mm, y,
               "This form captures the details submitted by the patient at "
               "the point of registration. All fields marked as required "
               "under the Ministry of Health National Standards for "
               "Medical Records must be completed before consultation.")
    y = _fields(c, 20 * mm, y, [
        ('Doc ID', 'doc_004'),
        ('Patient Name', 'Chloe Ng'),
        ('Date of Birth', '1994-11-02'),
        ('NRIC / FIN', 'S9456781D'),
        ('Policy Number', 'AIA-553102'),
        ('Allergies', ''),
        ('Consent Signed', 'Yes (2026-06-10)'),
    ])
    _footer(c, [
        'National Heart Centre Singapore Pte Ltd  ·  Company Reg No. 199801148C',
        'This form is a medical record. Unauthorised disclosure is an offence under the Personal Data Protection Act 2012.',
    ])
    _watermark(c); c.save()

    # Insurance card (Chloe)
    c = canvas.Canvas(str(d / 'insurance_ng.pdf'), pagesize=A4)
    y = _header(c, 'AIA Singapore', 'Health Shield Gold Max',
                AIA_BRAND,
                address='1 Robinson Road, AIA Tower, Singapore 048542',
                contact='Tel 1800 248 8000  ·  aia.com.sg')
    y = _title_block(c, 20 * mm, y, 'Health Insurance Card',
                     'Card image scanned by the clinic reception on registration.')
    y = _prose(c, 20 * mm, y,
               "Please present this card at the point of service. "
               "Cashless hospitalisation is available at all AIA-panel "
               "institutions. For pre-authorisation queries, quote the "
               "policy number printed below.")
    y -= 4 * mm
    _card_box(c, 20 * mm, y, 170 * mm, 50 * mm, AIA_BRAND)
    y = _fields(c, 25 * mm, y - 5 * mm, [
        ('Doc ID', 'doc_005'),
        ('Cardholder', 'Chloe Ng'),
        ('Policy Number', 'AIA-553120'),
        ('Plan', 'Health Shield Gold Max A'),
        ('Effective From', '2024-01-01'),
    ])
    _footer(c, [
        'AIA Singapore Private Limited  ·  Company Reg No. 201106386R  ·  1 Robinson Road, AIA Tower, Singapore 048542',
    ])
    _watermark(c); c.save()

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


# ---- Scanned image samples (for the Real-pile upload demo) -------------

def build_samples():
    d = OUT / 'samples'
    d.mkdir(parents=True, exist_ok=True)

    # a. NRIC card photo
    _render_id_card_png(d / 'nric_scan_chloe.png',
                        name='Chloe Ng',
                        nric='S9456781D',
                        dob='02 Nov 1994')

    # b. Scanned utility bill (Priya)
    _render_scan_jpeg(d / 'utility_bill_priya.jpg',
                      title='SP Group · Utility Bill',
                      brand=(0, 169, 206),
                      rows=[
                          ('Doc ID', 'doc_001'),
                          ('Account Holder', 'Priya Suresh'),
                          ('NRIC', 'S8712345B'),
                          ('Service Address', 'Blk 44 Toa Payoh Lor 5 #08-217'),
                          ('', 'Singapore 310044'),
                          ('Billing Period', '2026-06-01 to 2026-06-30'),
                          ('Amount Due', 'SGD 92.10'),
                      ])

    # c. Scanned employment letter (signed)
    _render_signed_letter_jpeg(
        d / 'employment_letter_priya.jpg',
        header='TechFlow Consulting',
        tagline='Global consulting services  ·  #22-01 Suntec Tower 5, Singapore 038985',
        brand=(11, 61, 145),
        body_paragraphs=[
            'Date: 2026-06-04',
            '',
            'To whom it may concern,',
            '',
            'This letter certifies that Priya Suresh (NRIC S8712345B) has '
            'been employed with TechFlow Consulting Pte Ltd since '
            '2019-03-11 as a Senior Consultant. Her current monthly gross '
            'salary is SGD 9,800.',
            'She may contact HR at hr@techflow.sg or +65 6812 4400 for any '
            'verification queries.',
        ],
        sign_off_name='Emily Tan',
        sign_off_title='Head of People, TechFlow Consulting Pte Ltd'
    )

    # d. README explaining the samples
    (d / 'README.md').write_text(
        '# scanned-doc samples\n\n'
        'A small set of image documents (PNG/JPEG) used to demo the Real-pile '
        'upload flow. These are NOT part of any pile\'s ground truth; drag '
        'them into the "Your pile" tab in the UI to see Gemma extract the '
        'fields live and Presidio redact identifiers.\n\n'
        '- `nric_scan_chloe.png` — Singapore NRIC-shaped ID card photo\n'
        '- `utility_bill_priya.jpg` — scanned utility bill with a rubber-stamp receipt marker\n'
        '- `employment_letter_priya.jpg` — signed employment verification letter\n'
    )


def build_readme():
    (OUT / 'README.md').write_text(
        '# paperflow synthetic data\n\n'
        'Three demo piles for the paperflow reconciler. Regenerate with:\n\n'
        '    python3 generate_synthetic.py\n\n'
        '## piles\n\n'
        '- `kyc_onboarding/` — 4 documents (KYC form, utility bill, NRIC scan, email declaration)\n'
        '- `partner_collation/` — 6 documents (registration sheets, MoU, business card, email)\n'
        '- `patient_intake/` — 5 documents (intake forms, referral letter, lab requisition, insurance card)\n\n'
        '`samples/` also contains scanned-image documents (PNG/JPEG) for the Real-pile upload demo.\n\n'
        '## visual style\n\n'
        'Each PDF is rendered with a company letterhead (brand mark + wordmark + '
        'coloured accent rule), a paragraph of domain-appropriate prose, the '
        'field data in a labelled block, and a legal footer. The KYC form spans '
        'two pages. Every planted VALUE stays identical across regenerations '
        "to keep the scorer's ground-truth stable.\n\n"
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
    build_samples()
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
