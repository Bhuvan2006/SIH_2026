"""
Merges the "India Medicines and Drug Info Dataset" (1mg scrape) into the
medicine_products catalogue.

    python scripts/import_1mg_dataset.py "India Medicines and Drug Info Dataset.csv"

Run scripts/import_indian_medicines.py FIRST. This script builds on it: it
reuses that import's ~1,650-ingredient vocabulary to disambiguate the CSV's
run-together columns (see parse_1mg_blob), and it upgrades rows that import
created rather than duplicating them.

Three things this dataset adds that the other one does not have:

  1. ~105,000 medicines absent from the Indian-Medicine-Dataset.
  2. COMPLETE composition. The other source has only two composition columns,
     so every three-ingredient combination was silently indexed as a
     two-ingredient one -- meaning price comparison could offer a "same
     composition" swap that is missing a molecule. This file lists all of
     them, so overlapping products get their composition corrected.
  3. Prescription-required vs over-the-counter, which nothing else here knew.

What it deliberately does NOT take from this dataset:

  * Image URLs. There are three distinct URLs across 348,211 rows; 348,203 of
    them share one placeholder.
  * The `Price` column, which is rounded to whole rupees. The blob's "MRP" is
    exact and is parsed instead.
  * The `Type of Medicine` / `Composition` columns, which are empty on ~30% of
    rows and mis-split on the rest.

Rows the parser cannot read (~0.2%) are counted and skipped, never guessed at.
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import func  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.models.models import MedicineProduct  # noqa: E402
from import_indian_medicines import (  # noqa: E402
    GENERIC_HINTS,
    build_curated_index,
    composition_key,
    norm_ingredient,
    parse_dose_form,
    parse_pack_count,
    parse_strengths,
)
from parse_1mg_blob import parse_row  # noqa: E402

SOURCE = "india_medicines_1mg"
BATCH = 5000

# csv.field_size_limit's default is far below the size of the scraped
# "Product Name" blob on some rows.
csv.field_size_limit(10_000_000)


def split_composition(composition: str) -> list[str]:
    """'Aspirin (75mg) + Rosuvastatin (20mg) + Clopidogrel (75mg)' -> three parts.

    Unlike the other dataset there is no two-ingredient ceiling here, which is
    the whole point of this import.
    """
    return [p.strip() for p in (composition or "").split("+") if p.strip()]


def derive_keys(composition: str, pack_label: str, price: float | None) -> dict:
    parts = split_composition(composition)
    key = composition_key(*parts)
    strengths = parse_strengths(*parts)
    dose_form = parse_dose_form(pack_label or "")
    pack_count = parse_pack_count(pack_label or "")
    per_unit = round(price / pack_count, 4) if price is not None and pack_count else price
    return {
        "composition_key": key or None,
        "strength_key": strengths or None,
        "dose_form": dose_form,
        "pack_count": pack_count,
        "price_per_unit": per_unit,
        "formulation_key": "|".join([key, strengths, dose_form or ""]) if key else None,
    }


def load_ingredient_vocabulary(db) -> set[str]:
    vocab: set[str] = set()
    for (key,) in db.query(MedicineProduct.composition_key).distinct().all():
        if key:
            vocab.update(part.strip() for part in key.split("+") if part.strip())
    # The other importer normalises spellings on the way in ("amoxycillin" ->
    # "amoxicillin"), so the stored keys never contain the spelling this file
    # actually uses. Add both directions.
    from import_indian_medicines import SPELLING_ALIASES

    vocab.update(SPELLING_ALIASES.keys())
    vocab.update(SPELLING_ALIASES.values())
    return vocab


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv_path", type=Path)
    ap.add_argument("--limit", type=int, default=0, help="Read at most N rows (quick test run).")
    ap.add_argument(
        "--no-upgrade",
        action="store_true",
        help="Only insert new medicines; leave existing rows' composition untouched.",
    )
    args = ap.parse_args()

    if not args.csv_path.exists():
        sys.exit(f"not found: {args.csv_path}")

    db = SessionLocal()
    try:
        vocab = load_ingredient_vocabulary(db)
        curated = build_curated_index(db)
        print(f"ingredient vocabulary : {len(vocab)}")
        print(f"curated drug keys     : {len(curated)}")

        # name_key -> id, for deciding insert vs upgrade.
        existing: dict[str, str] = {
            k: i for k, i in db.query(MedicineProduct.name_key, MedicineProduct.id).all()
        }
        print(f"catalogue rows        : {len(existing):,}")

        inserts: list[dict] = []
        upgrades: list[dict] = []
        seen: set[str] = set()
        read = parsed = duplicate = unreadable = 0
        richer = 0

        with args.csv_path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                read += 1
                if args.limit and read > args.limit:
                    break

                p = parse_row(row.get("Product Name", ""), row.get("Medicine Name", ""), vocab)
                if p.unparsed_reason or not p.name or not p.composition:
                    unreadable += 1
                    continue

                name_key = " ".join(p.name.lower().split())
                if name_key in seen:
                    # The file has ~97,000 duplicate rows; first one wins.
                    duplicate += 1
                    continue
                seen.add(name_key)
                parsed += 1

                keys = derive_keys(p.composition, p.pack_size_label or "", p.price_inr)
                drug_id = curated.get(keys["composition_key"] or "")
                ingredient_count = len(split_composition(p.composition))

                if name_key in existing:
                    if args.no_upgrade:
                        continue
                    upgrades.append(
                        {
                            "id": existing[name_key],
                            "composition": p.composition,
                            "prescription_required": p.prescription_required,
                            "drug_id": drug_id,
                            **keys,
                        }
                    )
                    if ingredient_count > 2:
                        richer += 1
                else:
                    lowered = p.name.lower()
                    inserts.append(
                        {
                            "name": p.name,
                            "name_key": name_key,
                            "manufacturer": p.manufacturer,
                            "price_inr": p.price_inr,
                            "pack_size_label": p.pack_size_label,
                            "composition": p.composition,
                            "is_discontinued": False,
                            "is_generic": any(h in lowered for h in GENERIC_HINTS),
                            "prescription_required": p.prescription_required,
                            "drug_id": drug_id,
                            "source": SOURCE,
                            **keys,
                        }
                    )

                if len(inserts) >= BATCH:
                    db.bulk_insert_mappings(MedicineProduct, inserts)
                    db.commit()
                    inserts.clear()
                if len(upgrades) >= BATCH:
                    db.bulk_update_mappings(MedicineProduct, upgrades)
                    db.commit()
                    upgrades.clear()
                if read % 25000 == 0:
                    print(f"  {read:,} rows read...", end="\r", flush=True)

        if inserts:
            db.bulk_insert_mappings(MedicineProduct, inserts)
        if upgrades:
            db.bulk_update_mappings(MedicineProduct, upgrades)
        db.commit()

        total = db.query(func.count(MedicineProduct.id)).scalar()
        rx_known = (
            db.query(func.count(MedicineProduct.id))
            .filter(MedicineProduct.prescription_required.isnot(None))
            .scalar()
        )
        otc = (
            db.query(func.count(MedicineProduct.id))
            .filter(MedicineProduct.prescription_required.is_(False))
            .scalar()
        )
        three_plus = (
            db.query(func.count(MedicineProduct.id))
            .filter(MedicineProduct.composition_key.like("%+%+%"))
            .scalar()
        )

        print(f"\nrows read              : {read:,}")
        print(f"unreadable (skipped)   : {unreadable:,} ({unreadable / max(read, 1):.2%})")
        print(f"duplicate names        : {duplicate:,}")
        print(f"usable products        : {parsed:,}")
        print(f"compositions corrected : {richer:,} now carry 3+ ingredients")
        print()
        print(f"medicine_products      : {total:,} rows")
        print(f"prescription status    : {rx_known:,} known ({otc:,} over-the-counter)")
        print(f"3+ ingredient formulas : {three_plus:,}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
