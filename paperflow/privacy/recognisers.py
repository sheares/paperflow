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
        # Catches OCR-corrupted NRIC-like strings (e.g. K3098S51, 5 -> S).
        # Lower score: flagged for review rather than silently trusted.
        PatternRecognizer(
            supported_entity="SG_NRIC_SUSPECT",
            name="sg_nric_suspect",
            patterns=[Pattern("nric_loose", r"\b[A-Z]\d{4}[A-Z0-9]\d{2}\b", 0.4)],
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
        # Postcode is context-gated to avoid mass 6-digit false positives.
        PatternRecognizer(
            supported_entity="SG_POSTCODE",
            name="sg_postcode",
            patterns=[Pattern("postcode", r"\b\d{6}\b", 0.3)],
            context=["singapore", "sg", "address", "blk", "ave", "street", "st", "road"],
        ),
    ]
