"""
Extracts the CDSCO list of drugs prohibited under section 26A of the Drugs &
Cosmetics Act 1940 from the official PDF into app/data/banned_drugs_cdsco.json.

    python scripts/parse_cdsco_banned_pdf.py path/to/banned_drugs.pdf

The PDF has no extractable text layer -- every glyph is a vector path -- so
pages are rasterised with PyMuPDF and read with Tesseract. The "Notification
No. & Date" column is cropped away before OCR: left in, its wrapped lines
interleave with the drug names and corrupt them.

Rows are cut on the table's own ruled lines, which ARE in the file as vector
paths even though the text is not. Reconstructing rows from OCR line breaks
instead does not work: the scan drops the serial number on most wrapped rows,
and every heuristic for "new entry or continuation?" was wrong in one
direction or the other -- 524 entries when it split too eagerly, 188 when it
merged too eagerly, against a true count of 444. The ruled lines are exact, so
each entry is OCR'd from its own cell and the guessing disappears.

Most of the 444 entries are fixed-dose combinations ("Nimesulide +
Paracetamol suspension"), not single molecules, which is why this is worth
importing properly rather than by hand: matching them needs the ingredient
SET, and the medicine catalogue now carries full compositions to match
against.

Three caveats travel with this document and are preserved in the output
rather than dropped, because presenting a stayed or revoked prohibition as a
live ban would be wrong:

  *   stayed by the Madras High Court
  **  revoked with conditions (dextropropoxyphene, G.S.R. 367 of 13.04.2017)
  *** notifications S.O. 705(E)-1048(E) of 10.03.2016 quashed by the Delhi
      High Court on 01.12.2016; under appeal before the Supreme Court

OCR is not perfect on a 28-page scan. Entries are emitted with both their raw
text and, where the text parses cleanly into "A + B + C", a normalised
ingredient list; anything that does not parse keeps its raw form and is
matched as free text. Rows are counted, and the script prints what it could
not classify so the gap is visible rather than silent.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATA_DIR = Path(__file__).resolve().parent.parent / "app" / "data"
OUT_PATH = DATA_DIR / "banned_drugs_cdsco.json"

# The drug-name column, as a fraction of page width. The notification column
# starts around 0.80 and its wrapped lines corrupt the names if included.
# Starts just right of the rule between "Sr. No." and "Drugs Name". Including
# that rule made Tesseract fuse it with the first ingredient's opening letters
# ("Nimesulide" read as "Nines", "jNinesul", ")Piecomins"), which is exactly
# the word a ban rule needs to be right about. The serial number is lost with
# it; entries are numbered by position instead, which is more reliable anyway.
COLUMN_LEFT = 0.22
COLUMN_RIGHT = 0.80
RENDER_DPI = 400

# Lines that are pure OCR noise: table rules and marginalia read as letters.
NOISE_RE = re.compile(
    r"^(?:[|\[\]_\-—=~`'\"^*.,;:()]+|[A-Za-z]{1,3}\s*[|\[\]]+.*|KKK|kkk|ees|cata|oe|Pe|PS|xX+)$"
)

ENTRY_START_RE = re.compile(r"^(\d{1,3})\s*[.)]\s*(.*)$")

# A continuation of the previous line rather than a new entry: OCR drops the
# serial number on wrapped rows, so the only signal left is that the line
# cannot be the start of a drug name.
CONTINUATION_RE = re.compile(r"^(?:[a-z+&/(]|and\b|or\b|with\b|\+)")

FOOTNOTE_MARKERS = {
    "*": "stayed_madras_hc",
    "**": "revoked_with_conditions",
    "***": "quashed_delhi_hc_under_appeal",
}

CAVEAT_TEXT = {
    "stayed_madras_hc": (
        "This prohibition is currently stayed by the Madras High Court, so the "
        "medicine may still be legally on sale while the case is decided."
    ),
    "revoked_with_conditions": (
        "This prohibition was revoked with conditions (G.S.R. 367, 13.04.2017): the "
        "drug is permitted for cancer pain only, at no more than 300 mg per day."
    ),
    "quashed_delhi_hc_under_appeal": (
        "The notification behind this entry was quashed by the Delhi High Court on "
        "01.12.2016 and is under appeal before the Supreme Court, so its legal "
        "status is unsettled."
    ),
}

# Words that are part of a formulation description, not an ingredient.
FORM_NOISE = re.compile(
    r"\b(suspension|tablets?|capsules?|syrup|injection|dispersible|dispesible|"
    r"enteric coated|oral|drops?|gel|cream|kit|sr|er|combikit of \d+|units?)\b",
    re.IGNORECASE,
)


def load_ingredient_vocabulary() -> list[str]:
    """
    Every distinct active ingredient in the imported medicine catalogue
    (~1,700 molecules). Used to repair OCR damage: a scanned "-aracetamol" or
    "Nimesstce" is unambiguous against a fixed vocabulary, and a ban rule that
    silently keeps the misspelling would never match anything.
    """
    try:
        from app.db.database import SessionLocal
        from app.models.models import MedicineProduct
    except Exception:  # noqa: BLE001 - the script must still run without a DB
        return []

    db = SessionLocal()
    try:
        vocab: set[str] = set()
        for (key,) in db.query(MedicineProduct.composition_key).distinct().all():
            if key:
                vocab.update(part.strip() for part in key.split("+") if len(part.strip()) > 2)
        return sorted(vocab)
    finally:
        db.close()


def correct_ingredient(name: str, vocabulary: list[str]) -> tuple[str, bool]:
    """Returns (best name, was_corrected). Leaves the raw text alone when no
    vocabulary entry is close enough -- a wrong correction is worse than none."""
    if not name or not vocabulary or name in vocabulary:
        return name, False

    from rapidfuzz import process, fuzz

    hit = process.extractOne(name, vocabulary, scorer=fuzz.ratio, score_cutoff=82)
    if hit:
        return hit[0], hit[0] != name
    return name, False


def rasterise(pdf_path: Path, out_dir: Path) -> list[Path]:
    import pymupdf

    doc = pymupdf.open(pdf_path)
    pages = []
    for i in range(doc.page_count):
        pix = doc[i].get_pixmap(dpi=RENDER_DPI)
        target = out_dir / f"page_{i + 1:02d}.png"
        pix.save(target)
        pages.append(target)
    return pages


def row_boundaries(page) -> list[float]:
    """
    The y positions (in PDF points) of the table's horizontal rules, which
    PyMuPDF reads as vector paths even though the glyphs are unreadable.
    Near-duplicates are collapsed: a ruled line is often drawn as two
    overlapping paths a fraction of a point apart.
    """
    ys: list[float] = []
    for item in page.get_drawings():
        rect = item["rect"]
        if rect.width > 300 and rect.height < 4:
            ys.append(rect.y0)
        for op in item["items"]:
            if op[0] == "l":
                a, b = op[1], op[2]
                if abs(a.y - b.y) < 1.5 and abs(a.x - b.x) > 300:
                    ys.append(a.y)

    merged: list[float] = []
    for y in sorted(ys):
        if not merged or y - merged[-1] > 3.0:
            merged.append(y)

    # The table's closing border is not always drawn as a long horizontal path,
    # so without this the LAST row of every page is silently dropped -- 28
    # pages, 28 missing entries. The vertical column borders do reach the
    # bottom of the table, so their lowest extent is the closing boundary.
    if merged:
        verticals = [
            item["rect"].y1
            for item in page.get_drawings()
            if item["rect"].height > 20 and item["rect"].width < 6
        ]
        if verticals:
            bottom = max(verticals)
            if bottom - merged[-1] > 12.0:
                merged.append(bottom)

    return merged


def crop_cells(page_png: Path, boundaries: list[float], page_height_pt: float) -> list[Path]:
    """One image per table row, covering the drug-name column only."""
    from PIL import Image

    im = Image.open(page_png)
    w, h = im.size
    scale = h / page_height_pt
    left, right = int(w * COLUMN_LEFT), int(w * COLUMN_RIGHT)

    cells: list[Path] = []
    for index, (top, bottom) in enumerate(zip(boundaries, boundaries[1:])):
        y0, y1 = int(top * scale), int(bottom * scale)
        if y1 - y0 < 12:  # a rule pair, not a row
            continue
        # A little padding keeps descenders while stopping the rule itself
        # from being read as a character.
        target = page_png.with_name(f"{page_png.stem}_cell_{index:02d}.png")
        im.crop((left, max(0, y0 + 2), right, min(h, y1 - 2))).save(target)
        cells.append(target)
    return cells


def ocr(image: Path, tesseract: str, tessdata: str | None) -> str:
    env_arg = ["--tessdata-dir", tessdata] if tessdata else []
    out = image.with_suffix("")
    subprocess.run(
        [tesseract, str(image), str(out), "--psm", "6", *env_arg],
        check=True,
        capture_output=True,
    )
    return out.with_suffix(".txt").read_text(encoding="utf-8", errors="replace")


def clean_line(line: str) -> str:
    line = line.replace("|", " ").strip()
    return re.sub(r"\s+", " ", line)


def split_entries(text: str) -> list[tuple[int | None, str]]:
    """
    Rebuilds numbered entries from OCR lines. Serial numbers are dropped by OCR
    on many wrapped rows, so a line that cannot start a drug name (it begins
    lowercase, or with "+", "and", "with") is folded into the previous entry.
    """
    entries: list[tuple[int | None, str]] = []
    for raw in text.splitlines():
        line = clean_line(raw)
        if not line or NOISE_RE.match(line):
            continue
        # Page furniture.
        if re.match(r"^(LIST OF DRUGS|GAZETTE|ACT 1940|Drugs Name|Sr\.? No)", line, re.I):
            continue
        # Footnote explanations at the end of the document.
        if line.startswith(("*Presently", "** prohibition", "*** The Notification", "(a)", "(b)", "(c)", "e ")):
            continue

        m = ENTRY_START_RE.match(line)
        if m:
            entries.append((int(m.group(1)), m.group(2).strip()))
            continue

        # No serial number. Decide continuation vs new entry.
        #
        # The lowercase/"+"/"and" test alone was not enough: a wrapped line can
        # begin with a capital ("...Atropine in Analgesics and" / "Antipyretics."),
        # and treating those as new entries split 444 rows into 524. Every real
        # entry in this document ends with a full stop or a complete ingredient
        # name, so an unfinished previous entry is the reliable signal.
        if entries:
            _, previous = entries[-1]
            previous_unfinished = not previous.rstrip().endswith(".") or previous.rstrip().endswith(
                ("and.", "or.", "with.")
            )
            if CONTINUATION_RE.match(line) or previous_unfinished:
                number, body = entries[-1]
                entries[-1] = (number, f"{body} {line}".strip())
                continue

        entries.append((None, line))
    return entries


def extract_markers(text: str) -> tuple[str, str | None]:
    """Pulls a trailing/leading footnote marker off an entry, longest first."""
    caveat = None
    for marker in ("***", "**", "*"):
        if marker in text:
            caveat = FOOTNOTE_MARKERS[marker]
            text = text.replace(marker, " ")
            break
    return re.sub(r"\s+", " ", text).strip(), caveat


def normalise_ingredient(part: str) -> str:
    part = FORM_NOISE.sub(" ", part)
    part = re.sub(r"\(.*?\)", " ", part)
    part = re.sub(r"\d+\s*(mg|mcg|g|ml|%)\b", " ", part, flags=re.IGNORECASE)
    part = re.sub(r"[^A-Za-z\s-]", " ", part)
    return re.sub(r"\s+", " ", part).strip().lower()


def parse_entry(number: int | None, text: str, vocabulary: list[str]) -> dict | None:
    text, caveat = extract_markers(text)
    if len(text) < 4:
        return None

    lowered = text.lower()

    # "Fixed dose combinations of X with any other drug ..." are class rules,
    # not ingredient lists -- matching them needs judgement we do not have, so
    # they are stored as free text and matched on their leading molecule only.
    is_class_rule = bool(
        re.search(
            r"any other drug|any other|group of drugs|except|all fixed dose|"
            r"with other drugs|in tonics|preparations containing",
            lowered,
        )
    )
    # "Fixed dose combinations of X with Y" written in prose rather than as
    # "X + Y" is a class rule too: we cannot turn "antihistaminic with
    # anti-diarrhoeals" into two matchable molecule names.
    if not is_class_rule and lowered.startswith("fixed dose combination") and "+" not in text:
        is_class_rule = True

    ingredients: list[str] = []
    if "+" in text and not is_class_rule:
        parts = [normalise_ingredient(p) for p in text.split("+")]
        ingredients = [p for p in parts if len(p) >= 3]

    if not ingredients and not is_class_rule:
        single = normalise_ingredient(re.sub(r"^fixed dose combinations? of\s*", "", lowered))
        # A single-molecule entry is one short phrase ("amidopyrine",
        # "phenacetin"). Anything longer is prose we should not turn into a
        # match rule.
        if single and len(single.split()) <= 3:
            ingredients = [single]

    corrected: list[str] = []
    ocr_corrections = 0
    for name in ingredients:
        best, changed = correct_ingredient(name, vocabulary)
        corrected.append(best)
        ocr_corrections += int(changed)

    return {
        "serial": number,
        "text": text,
        "ingredients": corrected,
        "ocr_corrections": ocr_corrections,
        "kind": (
            "class_rule" if is_class_rule
            else "combination" if len(corrected) > 1
            else "single" if corrected
            else "unclassified"
        ),
        "caveat": caveat,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf_path", type=Path)
    ap.add_argument(
        "--tesseract",
        default=r"C:\Users\bhuva\.conda\envs\tesseract\Library\bin\tesseract.exe",
        help="Path to the tesseract binary.",
    )
    ap.add_argument(
        "--tessdata",
        default=r"C:\Users\bhuva\.conda\envs\tesseract\share\tessdata",
        help="Path to the tessdata directory.",
    )
    ap.add_argument("--keep-scratch", action="store_true")
    args = ap.parse_args()

    if not args.pdf_path.exists():
        sys.exit(f"not found: {args.pdf_path}")
    if not shutil.which(args.tesseract) and not Path(args.tesseract).exists():
        sys.exit(f"tesseract not found at {args.tesseract}")

    scratch = Path(tempfile.mkdtemp(prefix="cdsco_"))
    try:
        pages = rasterise(args.pdf_path, scratch)
        print(f"rasterised {len(pages)} pages at {RENDER_DPI} dpi")

        import pymupdf

        doc = pymupdf.open(args.pdf_path)
        raw_entries: list[tuple[int | None, str]] = []
        for index, page_png in enumerate(pages):
            page = doc[index]
            boundaries = row_boundaries(page)
            for cell in crop_cells(page_png, boundaries, page.rect.height):
                # One cell, one entry. --psm 6 reads the wrapped lines inside
                # it as a single block, which is exactly what a table cell is.
                joined = " ".join(
                    clean_line(line)
                    for line in ocr(cell, args.tesseract, args.tessdata).splitlines()
                    if clean_line(line)
                ).strip()
                if not joined or NOISE_RE.match(joined):
                    continue
                if re.match(r"^(LIST OF DRUGS|GAZETTE|ACT 1940|Drugs? Name|Sr\.? No)", joined, re.I):
                    continue
                if joined.startswith(("*Presently", "** prohibition", "*** The Notification")):
                    continue
                match = ENTRY_START_RE.match(joined)
                if match:
                    raw_entries.append((int(match.group(1)), match.group(2).strip()))
                else:
                    raw_entries.append((None, joined))
            print(f"  page {index + 1}/{len(pages)}", end="\r", flush=True)

        vocabulary = load_ingredient_vocabulary()
        print(f"ingredient vocabulary: {len(vocabulary)} molecules")

        parsed = []
        for position, (number, text) in enumerate(raw_entries, start=1):
            entry = parse_entry(number or position, text, vocabulary)
            if entry:
                parsed.append(entry)

        by_kind: dict[str, int] = {}
        for entry in parsed:
            by_kind[entry["kind"]] = by_kind.get(entry["kind"], 0) + 1

        payload = {
            "_note": (
                "List of drugs prohibited for manufacture and sale through gazette "
                "notifications under section 26A of the Drugs & Cosmetics Act 1940, "
                "Ministry of Health and Family Welfare. Extracted by OCR from the "
                "official CDSCO PDF (see scripts/parse_cdsco_banned_pdf.py), so "
                "occasional spelling errors from the scan are possible -- entries "
                "keep their raw text alongside the parsed ingredients. Some entries "
                "are stayed, revoked, or under appeal; see the 'caveat' field and "
                "_caveats below. Re-verify against https://cdsco.gov.in before any "
                "clinical or production use."
            ),
            "_source": "CDSCO / Ministry of Health and Family Welfare, section 26A list",
            "_caveats": CAVEAT_TEXT,
            "_counts": by_kind,
            "entries": parsed,
        }
        OUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        corrections = sum(e["ocr_corrections"] for e in parsed)
        print(f"entries parsed : {len(parsed)}")
        print(f"OCR repairs    : {corrections} ingredient names matched to the catalogue vocabulary")
        for kind, count in sorted(by_kind.items()):
            print(f"  {kind:<14} {count}")
        print(f"written        : {OUT_PATH}")

        unclassified = [e for e in parsed if e["kind"] == "unclassified"][:10]
        if unclassified:
            print("\nsample unclassified (kept as free text, matched loosely):")
            for e in unclassified:
                print(f"  - {e['text'][:88]}")
    finally:
        if args.keep_scratch:
            print(f"scratch kept at {scratch}")
        else:
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
