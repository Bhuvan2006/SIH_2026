"""
Parser for the "India Medicines and Drug Info Dataset" (1mg scrape) CSV.

That file's columns cannot be trusted. `Type of Medicine` and `Composition`
are empty on ~30% of rows, and where they are populated they are split in the
wrong place -- the first active ingredient is glued to the end of the
manufacturer name ("...Alpic Biotech LtdAspirin"), and its strength is stranded
at the start of the next column.

The `Product Name` column, however, is the whole scraped card and is populated
on every row, in a fixed order:

    {name}MRP RS{price}{"Prescription Required"?}{pack}{manufacturer}{composition}{"ADD"|"not available"}

with no separators. So everything is parsed out of that one field instead,
which gives one code path that works for all rows rather than two that each
work for some.

The only genuinely ambiguous boundary is manufacturer/composition, since
"LtdAspirin" has no delimiter. That is resolved by splitting at lowercase-to-
uppercase transitions and accepting the split whose tail is a known active
ingredient -- the vocabulary being the ~1,700 ingredients already imported from
the Indian-Medicine-Dataset. A row whose ingredient we cannot recognise is
reported as unparsed rather than guessed at.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

RUPEE = "₹"

# Container words a pack label can start with, longest first so "strip" does
# not shadow anything.
CONTAINERS = (
    "strip", "bottle", "vial", "tube", "packet", "pack", "jar", "box", "bag",
    "carton", "sachet", "ampoule", "prefilled syringe", "cartridge", "tin",
    "container", "unit", "dispenser", "can", "kit", "pen", "device", "roll",
    "tray", "card", "combipack", "sheet", "pump bottle", "spray bottle",
    "nasal spray", "vial pack", "pouch", "bucket", "refill",
)

# Dosage forms as they appear in this file (capitalised, unlike the other
# dataset). Longest first: "Oral Suspension" must win over "Suspension".
# Listed in the SINGULAR: the regex appends an optional "s", so "Eye Drop"
# also matches "Eye Drops". Listing the plural instead made the pattern
# require "Eye Dropss" and silently failed every eye-drop row.
FORM_WORDS = (
    "Powder For Injection", "Powder for Injection", "Oral Suspension", "Oral Solution",
    "Disintegrating Strip", "Oral Drop", "Eye Drop", "Ear Drop", "Eye Ointment",
    "Nasal Spray", "Nasal Drop", "Dry Syrup", "Mouth Paint", "Toothpaste",
    "Injection", "Suspension", "Solution", "Capsule", "Tablet", "Syrup",
    "Cream", "Ointment", "Lotion", "Powder", "Sachet", "Inhaler", "Respule",
    "Rotacap", "Spray", "Drop", "Gel", "Soap", "Shampoo", "Infusion", "Granule",
    "Liquid", "Paste", "Patch", "Wafer", "Film", "Emulsion", "Foam", "Lozenge",
    "Suppository", "Enema", "Mouthwash", "Redimix", "Bar", "Cap", "Kit",
    "Expectorant", "Rheocap", "Elixir", "Tincture", "Linctus", "Mixture",
    "Nebuliser Solution", "Transpule", "Pessary", "Insert", "Cartridge",
    "Mouth Wash", "Gargle", "Douche", "Scrub", "Serum", "Oil", "Ampoule",
    "Prefilled Syringe", "Suppositorie", "Vaginal Tablet", "Chewable Tablet",
)

FORM_MODIFIERS = ("SR", "ER", "XR", "CR", "DT", "MD", "MR", "XL", "LA", "OD")

TRAILERS = ("not available", "ADD", "Sold Out", "out of stock")

PRICE_RE = re.compile(r"MRP\s*" + RUPEE + r"\s*([0-9]+(?:\.[0-9]+)?)")
RX_MARKER = "Prescription Required"

# Two kinds of seam. The common one is lowercase-to-capital
# ("...Pvt LtdEthosuximide"). The second covers manufacturers ending in an
# all-caps suffix -- "Biozoc INCDomperidone", "Vonartes Pharmaceutical
# LLPAtorvastatin" -- where the join is capital-to-capital and only the
# following lowercase letter shows where the ingredient begins.
SEAM_RE = re.compile(r"(?<=[a-z0-9).])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

LEAD_SPLIT_RE = re.compile(r"\s*[(+]")

# A capitalised word (or two) immediately followed by a bracketed strength --
# what an active ingredient looks like: "Ethosuximide (250mg/5ml)".
BRACKETED_STRENGTH_RE = re.compile(r"^[A-Z][A-Za-z-]*(?:\s+[A-Za-z-]+){0,3}\s*\(")

# Two details in the plural, both learned the hard way:
#   * Without any "s?" at all, "strip of 10 tablets" matched only through
#     "tablet" and the stray plural was glued to the manufacturer
#     ("sAlpic Biotech Ltd").
#   * With a plain "s?" under this pattern's global IGNORECASE, it also
#     matched a CAPITAL S, so "Eye DropStelon Biotech" swallowed the
#     manufacturer's own initial and left "telon Biotech Private Limited".
# The scoped (?-i:s)? matches a lowercase plural only.
_pack_re = re.compile(
    r"^\s*(?:" + "|".join(CONTAINERS) + r")\b.*?\b(?:"
    + "|".join(re.escape(f) for f in FORM_WORDS)
    + r")(?-i:s)?(?:\s+(?:" + "|".join(FORM_MODIFIERS) + r"))?",
    re.IGNORECASE,
)


@dataclass
class ParsedRow:
    name: str
    price_inr: float | None
    prescription_required: bool
    pack_size_label: str | None
    manufacturer: str | None
    composition: str | None
    unparsed_reason: str | None = None


def _strip_trailer(text: str) -> str:
    for t in TRAILERS:
        if text.endswith(t):
            return text[: -len(t)].rstrip()
    return text


def split_manufacturer_composition(text: str, known_ingredients: set[str]) -> tuple[str | None, str | None]:
    """
    "Aci Pharma Pvt LtdEthosuximide (250mg/5ml)" ->
        ("Aci Pharma Pvt Ltd", "Ethosuximide (250mg/5ml)")

    Tries each lowercase-to-uppercase seam, latest first (manufacturer names
    contain capitals too -- "Aci Pharma Pvt Ltd" has three), and takes the
    first split whose tail begins with a recognised ingredient. Returns
    (None, None) when nothing matches, so the caller can count the row as
    unparsed rather than store a guess.
    """
    seams = [m.start() for m in SEAM_RE.finditer(text)]

    # Preferred: the tail starts with an ingredient we already know from the
    # Indian-Medicine-Dataset import. Latest seam first, because manufacturer
    # names carry capitals of their own ("Aci Pharma Pvt Ltd" has three).
    for pos in reversed(seams):
        head, tail = text[:pos].rstrip(), text[pos:].strip()
        if not tail:
            continue
        # The ingredient runs up to its strength "(...)", a "+" separator, or
        # the end of the string.
        lead = LEAD_SPLIT_RE.split(tail, maxsplit=1)[0].strip().lower()
        if lead and lead in known_ingredients:
            return (head or None), tail

    # Fallback for ingredients outside that vocabulary (it covers ~1,650
    # molecules, this file has more). Structurally the manufacturer/ingredient
    # join is the last seam followed by a bracketed strength, since neither
    # " + " nor a space-separated second word ("Clavulanic Acid") creates a
    # seam.
    #
    # It has to be the last *qualifying* seam, not simply the last one:
    # strengths like "(60Million spores)" contain a digit-to-capital seam of
    # their own, and taking that one blindly yielded "Million spores)" as the
    # composition for every probiotic combination in the file.
    for pos in reversed(seams):
        head, tail = text[:pos].rstrip(), text[pos:].strip()
        if BRACKETED_STRENGTH_RE.match(tail):
            return (head or None), tail

    return None, None


def parse_row(
    blob: str,
    medicine_name: str,
    known_ingredients: set[str],
) -> ParsedRow:
    blob = (blob or "").strip()
    name = (medicine_name or "").strip()

    price_match = PRICE_RE.search(blob)
    price = float(price_match.group(1)) if price_match else None

    if not price_match:
        return ParsedRow(name, None, True, None, None, None, "no MRP in blob")

    rest = blob[price_match.end():]

    prescription_required = rest.startswith(RX_MARKER)
    if prescription_required:
        rest = rest[len(RX_MARKER):]

    rest = _strip_trailer(rest.strip())

    pack_match = _pack_re.match(rest)
    if not pack_match:
        return ParsedRow(name, price, prescription_required, None, None, None, "no pack label")

    pack = pack_match.group(0).strip()
    remainder = rest[pack_match.end():].strip()

    manufacturer, composition = split_manufacturer_composition(remainder, known_ingredients)
    if composition is None:
        return ParsedRow(
            name, price, prescription_required, pack, None, None, "ingredient not recognised"
        )

    return ParsedRow(name, price, prescription_required, pack, manufacturer, composition)
