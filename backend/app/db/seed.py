"""
Loads the curated JSON sample data (app/data/*.json) into the database.
Idempotent: skips seeding if drug_knowledge already has rows.
"""
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.models import DrugKnowledge, PriceEntry, Pharmacy

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def seed_if_empty(db: Session) -> None:
    if db.query(DrugKnowledge).count() > 0:
        return  # already seeded

    drugs_raw = json.loads((DATA_DIR / "drug_knowledge.json").read_text(encoding="utf-8"))
    name_to_id: dict[str, str] = {}

    for d in drugs_raw:
        drug = DrugKnowledge(
            generic_name=d["generic_name"],
            brand_names=json.dumps(d.get("brand_names", [])),
            composition=d["composition"],
            strength=d.get("strength"),
            drug_class=d.get("drug_class"),
            route=d.get("route"),
            storage_instructions=d.get("storage_instructions"),
            common_interactions=json.dumps(d.get("common_interactions", [])),
            contraindications=json.dumps(d.get("contraindications", [])),
            conditions_treated=json.dumps(d.get("conditions_treated", [])),
            source_citation=d.get("source_citation"),
        )
        db.add(drug)
        db.flush()  # get drug.id
        name_to_id[d["generic_name"]] = drug.id

    price_raw = json.loads((DATA_DIR / "price_data.json").read_text(encoding="utf-8"))
    for generic_name, entries in price_raw.get("entries", {}).items():
        drug_id = name_to_id.get(generic_name)
        if not drug_id:
            continue
        for e in entries:
            db.add(
                PriceEntry(
                    drug_id=drug_id,
                    product_name=e["product_name"],
                    manufacturer=e.get("manufacturer"),
                    is_generic=e.get("is_generic", False),
                    price_inr=e["price_inr"],
                    unit=e.get("unit", "per strip of 10 tablets"),
                    source="sample_dataset",
                    last_updated="2026-08-24",
                )
            )

    pharmacies_raw = json.loads((DATA_DIR / "pharmacies.json").read_text(encoding="utf-8"))
    for p in pharmacies_raw.get("pharmacies", []):
        db.add(
            Pharmacy(
                name=p["name"],
                address=p["address"],
                latitude=p["latitude"],
                longitude=p["longitude"],
                phone=p.get("phone"),
                source="mock",
            )
        )

    db.commit()
