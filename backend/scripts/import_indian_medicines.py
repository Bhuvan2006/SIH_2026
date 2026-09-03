"""
Imports the open Indian-Medicine-Dataset into the medicine_products table.

    python scripts/import_indian_medicines.py path/to/indian_medicine_data.csv

Source: https://github.com/junioralive/Indian-Medicine-Dataset (MIT licensed,
~254,000 Indian branded medicines). Expected columns:

    id, name, price(Rs), Is_discontinued, manufacturer_name, type,
    pack_size_label, short_composition1, short_composition2

Why this matters more than the price numbers: the prototype shipped with 45
curated drugs, so OCR could only recognise a prescription if the doctor
happened to write one of 45 brand names. This adds a quarter of a million real
Indian brand names, each with its composition -- which is what turns "Abiros
CA" on a smudged prescription into "Aspirin + Rosuvastatin + Clopidogrel".

The clinical data does NOT come from here. Each product is linked back to a
curated DrugKnowledge row when its composition matches one, and safety
screening keeps reading only DrugKnowledge. Products with no match are
searchable and priceable but carry no safety verdict, and callers must say so
rather than implying the medicine was checked and cleared.

Idempotent: re-running replaces the imported rows (they are identified by
`source`), leaving curated data and patient data untouched.
"""
import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.models.models import DrugKnowledge, MedicineProduct  # noqa: E402

SOURCE = "indian_medicine_dataset"
BATCH = 5000

# The dataset's ingredient spellings vs. the curated set's. Left side is what
# appears in the CSV, right side is the curated generic_name it should link to.
SPELLING_ALIASES = {
    "amoxycillin": "amoxicillin",
    "paracetamol": "paracetamol",
    "acetaminophen": "paracetamol",
    "salbutamol": "salbutamol",
    "albuterol": "salbutamol",
    "frusemide": "furosemide",
    "thyroxine": "levothyroxine",
    "l-thyroxine": "levothyroxine",
    "cetrizine": "cetirizine",
    "cetirizine hydrochloride": "cetirizine",
    "metformin hydrochloride": "metformin",
    "glimepiride": "glimepiride",
    "rosuvastatin calcium": "rosuvastatin",
    "atorvastatin calcium": "atorvastatin",
}

# Markers that a product is a generic rather than a brand. Indian generics are
# usually sold under the molecule name itself.
GENERIC_HINTS = ("jan aushadhi", "generic")


def norm_ingredient(raw: str) -> str:
    """'Amoxycillin  (500mg) ' -> 'amoxicillin'. Strengths dropped on purpose:
    they belong to the product, not to the molecule."""
    s = re.sub(r"\(.*?\)", "", raw or "")
    s = s.replace(" ", " ")
    s = re.sub(r"\s+", " ", s).strip().strip(",").strip().lower()
    return SPELLING_ALIASES.get(s, s)


def composition_key(*parts: str) -> str:
    """Order-independent key so 'A + B' and 'B + A' are the same formulation."""
    ings = sorted({norm_ingredient(p) for p in parts if norm_ingredient(p)})
    return "+".join(ings)


# Pack labels are free text but highly regular: "strip of 10 tablets",
# "bottle of 60 ml oral suspension", "vial of 2 ml injection". The trailing
# words carry the dosage form and the leading number carries the pack count.
DOSE_FORMS = (
    ("powder for injection", "injection"),
    ("oral suspension", "suspension"),
    ("dry syrup", "syrup"),
    ("injection", "injection"),
    ("suspension", "suspension"),
    ("syrup", "syrup"),
    ("capsule", "capsule"),
    ("tablet", "tablet"),
    ("cream", "cream"),
    ("ointment", "ointment"),
    ("gel", "gel"),
    ("drop", "drops"),
    ("solution", "solution"),
    ("lotion", "lotion"),
    ("powder", "powder"),
    ("inhaler", "inhaler"),
    ("respule", "respule"),
    ("sachet", "sachet"),
    ("spray", "spray"),
    ("infusion", "infusion"),
)

# Modified-release and dispersible variants are genuinely different products --
# a sustained-release tablet is not swappable for a plain one -- so they get
# their own form rather than collapsing into "tablet".
FORM_MODIFIERS = ("sr", "er", "xr", "cr", "dt", "md", "mr", "xl", "la")


def parse_dose_form(pack_label: str) -> str | None:
    label = (pack_label or "").strip().lower()
    if not label:
        return None
    for needle, form in DOSE_FORMS:
        if needle in label:
            # "strip of 10 tablet sr" -> "tablet sr"
            tail = label.split(needle, 1)[1].strip().split()
            if tail and tail[0] in FORM_MODIFIERS:
                return f"{form} {tail[0]}"
            return form
    return None


def parse_pack_count(pack_label: str) -> int | None:
    """'strip of 10 tablets' -> 10. Volume packs ('bottle of 60 ml syrup')
    deliberately return None: millilitres are not doses, so a per-unit price
    computed from them would not mean anything."""
    label = (pack_label or "").strip().lower()
    m = re.search(r"\bof\s+(\d+)\s+(?!ml\b|gm\b|g\b|mg\b|mcg\b|litre\b|l\b)", label)
    if not m:
        return None
    try:
        n = int(m.group(1))
    except ValueError:
        return None
    return n if 0 < n <= 500 else None


def parse_strengths(*parts: str) -> str:
    """Strengths in the same order the ingredients are sorted into
    composition_key, so the two keys line up: 'amoxicillin+clavulanic acid'
    with '500mg+125mg'."""
    pairs = []
    for p in parts:
        ing = norm_ingredient(p)
        if not ing:
            continue
        m = re.search(r"\(([^)]*)\)", p or "")
        strength = re.sub(r"\s+", "", m.group(1)).lower() if m else ""
        pairs.append((ing, strength))
    pairs.sort(key=lambda kv: kv[0])
    return "+".join(st for _, st in pairs)


def readable_composition(*parts: str) -> str:
    cleaned = []
    for p in parts:
        p = re.sub(r"\s+", " ", (p or "").replace(" ", " ")).strip().strip(",").strip()
        if p:
            cleaned.append(p)
    return " + ".join(cleaned)


def build_curated_index(db) -> dict[str, str]:
    """
    Maps a composition key onto a curated drug id. A curated drug is indexed
    both by its generic name and by the ingredients parsed out of its
    composition string, so single-molecule products match either way.
    """
    index: dict[str, str] = {}
    for drug in db.query(DrugKnowledge).all():
        keys = {norm_ingredient(drug.generic_name)}
        # "Amoxicillin + Clavulanic acid" -> the combined key, so combination
        # products link to the combination drug rather than to one ingredient.
        parts = re.split(r"[+/]", drug.composition or "")
        combined = composition_key(*parts)
        if combined:
            keys.add(combined)
        for k in keys:
            if k:
                index.setdefault(k, drug.id)
    return index


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv_path", type=Path)
    ap.add_argument(
        "--include-discontinued",
        action="store_true",
        help="Import products marked discontinued (skipped by default -- a patient cannot buy them).",
    )
    ap.add_argument("--limit", type=int, default=0, help="Import at most N rows (for a quick test run).")
    args = ap.parse_args()

    if not args.csv_path.exists():
        sys.exit(f"not found: {args.csv_path}")

    db = SessionLocal()
    try:
        curated = build_curated_index(db)
        print(f"curated drugs indexed : {len(curated)} composition keys")

        removed = db.query(MedicineProduct).filter(MedicineProduct.source == SOURCE).delete()
        db.commit()
        if removed:
            print(f"cleared previous import: {removed} rows")

        imported = skipped_disc = linked = 0
        batch: list[dict] = []

        with args.csv_path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            price_col = next((c for c in reader.fieldnames or [] if c.startswith("price")), None)
            if not price_col:
                sys.exit(f"no price column in {reader.fieldnames}")

            for row in reader:
                if args.limit and imported >= args.limit:
                    break

                discontinued = (row.get("Is_discontinued") or "").strip().upper() == "TRUE"
                if discontinued and not args.include_discontinued:
                    skipped_disc += 1
                    continue

                name = (row.get("name") or "").strip()
                if not name:
                    continue

                c1, c2 = row.get("short_composition1", ""), row.get("short_composition2", "")
                key = composition_key(c1, c2)
                drug_id = curated.get(key)
                if drug_id:
                    linked += 1

                try:
                    price = float(row[price_col])
                except (TypeError, ValueError):
                    price = None

                lowered = name.lower()
                pack_label = (row.get("pack_size_label") or "").strip() or None
                dose_form = parse_dose_form(pack_label or "")
                pack_count = parse_pack_count(pack_label or "")
                strengths = parse_strengths(c1, c2)
                per_unit = (
                    round(price / pack_count, 4)
                    if price is not None and pack_count
                    else price
                )
                formulation = "|".join([key, strengths, dose_form or ""]) if key else None

                batch.append(
                    {
                        "name": name,
                        "name_key": lowered,
                        "manufacturer": (row.get("manufacturer_name") or "").strip() or None,
                        "price_inr": price,
                        "pack_size_label": pack_label,
                        "composition": readable_composition(c1, c2) or None,
                        "composition_key": key or None,
                        "strength_key": strengths or None,
                        "dose_form": dose_form,
                        "pack_count": pack_count,
                        "price_per_unit": per_unit,
                        "formulation_key": formulation,
                        "is_discontinued": discontinued,
                        "is_generic": any(h in lowered for h in GENERIC_HINTS),
                        "drug_id": drug_id,
                        "source": SOURCE,
                    }
                )
                imported += 1

                if len(batch) >= BATCH:
                    db.bulk_insert_mappings(MedicineProduct, batch)
                    db.commit()
                    batch.clear()
                    print(f"  {imported:,} imported...", end="\r", flush=True)

        if batch:
            db.bulk_insert_mappings(MedicineProduct, batch)
            db.commit()

        total = db.query(func.count(MedicineProduct.id)).scalar()
        distinct_comps = db.query(func.count(func.distinct(MedicineProduct.composition_key))).scalar()

        print(f"\nimported           : {imported:,}")
        print(f"skipped (discont.) : {skipped_disc:,}")
        print(f"linked to curated  : {linked:,} ({linked / imported:.1%} carry full safety data)")
        print(f"distinct formulas  : {distinct_comps:,}")
        print(f"medicine_products  : {total:,} rows total")
    finally:
        db.close()


if __name__ == "__main__":
    main()
