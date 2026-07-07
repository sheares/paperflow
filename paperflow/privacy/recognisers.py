"""Custom Presidio recognisers for the pile-specific identifier formats.

Regexes originate from the synthetic ground truth; the acceptance test is
that every `sensitive_spans` value in synthetic/*/ground_truth.json is
caught (see eval/).
"""
from presidio_analyzer import Pattern, PatternRecognizer

def get_recognisers() -> list[PatternRecognizer]:
    return [
        PatternRecognizer(
            supported_entity="SG_NRIC",
            name="sg_nric",
            patterns=[Pattern("nric", r"\b[STFGM]\d{7}[A-Z]\b", 0.9)],
        ),
        # Catches OCR-corrupted NRIC-like strings (e.g. K3098S51 or S7I22211Z,
        # a digit misread as a look-alike letter). Lower score: flagged for
        # review rather than silently trusted.
        PatternRecognizer(
            supported_entity="SG_NRIC_SUSPECT",
            name="sg_nric_suspect",
            patterns=[
                # 8-char serial form: letter + 7-char body with one substitution
                Pattern("nric_loose8", r"\b[A-Z]\d{4}[A-Z0-9]\d{2}\b", 0.4),
                # 9-char NRIC form: body of 7 with a letter where a digit
                # belongs (>=5 digits required so real words never match)
                Pattern("nric_loose9",
                        r"\b[STFGM](?=(?:[A-Z]?\d){5,})[0-9A-Z]{7}[A-Z]\b", 0.4),
            ],
        ),
        PatternRecognizer(
            supported_entity="SG_UEN",
            name="sg_uen_company",
            patterns=[Pattern("uen_co", r"\b\d{8,9}[A-Z]\b", 0.7)],
        ),
        PatternRecognizer(
            supported_entity="SG_UEN",
            name="sg_uen_llp",
            patterns=[Pattern("uen_llp", r"\bT\d{2}[A-Z]{2}\d{4}[A-Z]\b", 0.8)],
        ),
        PatternRecognizer(
            supported_entity="POLICY_NUMBER",
            name="policy_number",
            patterns=[Pattern("policy", r"\b(?:PRU|AIA|GE|NTUC)-?\d{6}\b", 0.85)],
        ),
        PatternRecognizer(
            supported_entity="SERIAL",
            name="lab_serial",
            patterns=[
                Pattern("labreq", r"\bLABREQ-\d{5}\b", 0.9),
                Pattern("serial_generic", r"\b[A-Z]{3,8}-\d{4,6}\b", 0.5),
            ],
        ),
        PatternRecognizer(
            supported_entity="SG_PHONE",
            name="sg_phone",
            patterns=[Pattern("phone", r"\+65[ -]?[689]\d{3}[ -]?\d{4}\b", 0.85)],
        ),
        # Labelled postcode ("Singapore 570210") is unambiguous.
        PatternRecognizer(
            supported_entity="SG_POSTCODE",
            name="sg_postcode_labelled",
            patterns=[Pattern("postcode_lbl", r"\bSingapore\s+\d{6}\b", 0.85)],
        ),
        # Bare postcode is context-gated to avoid mass 6-digit false positives.
        PatternRecognizer(
            supported_entity="SG_POSTCODE",
            name="sg_postcode",
            patterns=[Pattern("postcode", r"\b\d{6}\b", 0.3)],
            context=["singapore", "sg", "address", "blk", "ave", "street", "st", "road"],
        ),
        # SG street addresses: "Blk 210 Bishan St 23 #11-04", "8 Marina Boulevard #30-01"
        PatternRecognizer(
            supported_entity="SG_ADDRESS",
            name="sg_address",
            patterns=[Pattern(
                "sg_addr",
                r"\b(?:Blk\s+\d+|\d+)\s+[A-Za-z][A-Za-z0-9 .]*?#\d{2}-\d{2}\b",
                0.8,
            )],
        ),
        # ISO dates (DOBs and record dates in the piles)
        PatternRecognizer(
            supported_entity="ISO_DATE",
            name="iso_date",
            patterns=[Pattern("iso_date", r"\b\d{4}-\d{2}-\d{2}\b", 0.6)],
        ),
    ]
