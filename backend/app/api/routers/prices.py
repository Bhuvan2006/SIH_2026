import json

from fastapi import APIRouter, Depends, HTTPException, status
from rapidfuzz import fuzz
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.security import get_current_patient
from app.db.database import get_db
from app.models.models import DrugKnowledge, MedicineProduct, Patient
from app.services import price_service
from app.schemas.schemas import PriceComparisonResponse, PriceOption

router = APIRouter(prefix="/prices", tags=["price-comparison"])

PRICE_DISCLAIMER = price_service.DISCLAIMER

# Search results and /by-drug both key off "drug_id". A result that came from
# the bulk catalogue rather than the curated set has no curated drug, so its id
# is namespaced with this prefix -- which keeps one id field, one endpoint and
# one frontend code path instead of forking all three.
PRODUCT_ID_PREFIX = "product:"

# SQLite cannot use an index for LIKE 'x%' unless the index is declared
# COLLATE NOCASE, because its LIKE is case-insensitive by default. On a
# 351k-row table every prefix search therefore became a full scan, and a
# single request ran several of them (~2s per search). The equivalent range
# predicate does use the index. Safe here because name_key and
# composition_key are stored already-lowercased.
PREFIX_SENTINEL = "￿"


def _prefix(column, value: str):
    return and_(column >= value, column < value + PREFIX_SENTINEL)


def _build_response(db: Session, drug: DrugKnowledge) -> PriceComparisonResponse:
    options, cheapest = price_service.compare(
        db,
        formulation_key=price_service.formulation_key_for_drug(db, drug),
        drug=drug,
    )
    return PriceComparisonResponse(
        drug_id=drug.id,
        generic_name=drug.generic_name,
        composition=drug.composition,
        options=options,
        cheapest=cheapest,
        disclaimer=PRICE_DISCLAIMER,
    )


def _build_product_response(db: Session, product: MedicineProduct) -> PriceComparisonResponse:
    """
    Prices a catalogue product against every other product with the same
    composition, using the product's own MRP as the savings baseline.
    """
    options, cheapest = price_service.compare(
        db,
        formulation_key=product.formulation_key,
        drug=product.drug,
        reference_unit_price=product.price_per_unit or product.price_inr,
    )
    return PriceComparisonResponse(
        drug_id=PRODUCT_ID_PREFIX + product.id,
        generic_name=product.drug.generic_name if product.drug else product.name,
        composition=product.composition or "composition not listed",
        options=options,
        cheapest=cheapest,
        disclaimer=PRICE_DISCLAIMER,
    )


@router.get("/by-drug/{drug_id}", response_model=PriceComparisonResponse)
def price_comparison_by_drug(
    drug_id: str,
    db: Session = Depends(get_db),
    patient: Patient = Depends(get_current_patient),
):
    if drug_id.startswith(PRODUCT_ID_PREFIX):
        product = (
            db.query(MedicineProduct)
            .filter(MedicineProduct.id == drug_id[len(PRODUCT_ID_PREFIX):])
            .first()
        )
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medicine not found")
        return _build_product_response(db, product)

    drug = db.query(DrugKnowledge).filter(DrugKnowledge.id == drug_id).first()
    if not drug:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drug not found")
    return _build_response(db, drug)


@router.get("/search")
def search_drugs(q: str, db: Session = Depends(get_db), patient: Patient = Depends(get_current_patient)):
    """
    Name search returning drug_ids for /by-drug/{drug_id}.

    Matches generic name, BRAND names, and composition. Patients search for
    what is printed on the strip -- "Dolo", "Augmentin", "Glycomet" -- not the
    generic name, so a generic-only lookup silently returned nothing for the
    most common queries.
    """
    term = (q or "").strip()
    if not term:
        return []

    like = f"%{term}%"
    matches = (
        db.query(DrugKnowledge)
        .filter(
            or_(
                DrugKnowledge.generic_name.ilike(like),
                DrugKnowledge.brand_names.ilike(like),
                DrugKnowledge.composition.ilike(like),
            )
        )
        .limit(25)
        .all()
    )

    # Fuzzy fallback catches misspellings ("paracetmol", "azithromicin") that a
    # LIKE query misses entirely. Only consulted when the catalogue has nothing
    # either: at a 75 cutoff it is loose enough to return "Ondansetron" for
    # "zerodol", which is worse than no curated result when the catalogue holds
    # the real Zerodol brands.
    catalogue_has_exact = (
        db.query(MedicineProduct.id)
        .filter(_prefix(MedicineProduct.name_key, term.lower()))
        .first()
        is not None
    )
    if not matches and not catalogue_has_exact:
        all_drugs = db.query(DrugKnowledge).all()
        scored: list[tuple[float, DrugKnowledge]] = []
        for drug in all_drugs:
            names = [drug.generic_name] + json.loads(drug.brand_names or "[]")
            best = max((fuzz.partial_ratio(term.lower(), n.lower()) for n in names), default=0)
            # 75 let "paracetmol" pull back Ibuprofen and Ramipril. A
            # misspelling is a slip of a letter or two, not a different word.
            if best >= 85:
                scored.append((best, drug))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        matches = [drug for _, drug in scored[:10]]

    results = []
    for d in matches:
        brands = json.loads(d.brand_names or "[]")
        # Surface which brand matched, so the UI can show "Dolo 650 →
        # Paracetamol" instead of an unexplained generic name.
        matched_brand = next((b for b in brands if term.lower() in b.lower()), None)
        results.append(
            {
                "drug_id": d.id,
                "generic_name": d.generic_name,
                "composition": d.composition,
                "brand_names": brands,
                "matched_brand": matched_brand,
                "has_prices": True,
                "has_safety_data": True,
            }
        )

    # Then the bulk catalogue. The curated set covers a few dozen molecules;
    # nearly every real Indian brand a patient types lives only here. Results
    # are deduplicated by composition so searching "amlo" returns distinct
    # formulations rather than forty near-identical amlodipine strips.
    seen_compositions = {
        price_service.formulation_key_for_drug(db, d) for d in matches
    }
    remaining = 25 - len(results)
    if remaining > 0:
        lowered = term.lower()

        def _catalogue_query(*conditions):
            return (
                db.query(MedicineProduct)
                .filter(MedicineProduct.is_discontinued.is_(False), *conditions)
                .order_by(MedicineProduct.name_key.asc())
                .limit(400)
                .all()
            )

        # Indexed prefix lookups first. Both name_key and composition_key are
        # indexed, and a prefix predicate can use that index; a leading-wildcard
        # "%term%" cannot, and scanning 351k rows for it cost ~2s per search.
        products = _catalogue_query(
            or_(
                _prefix(MedicineProduct.name_key, lowered),
                _prefix(MedicineProduct.composition_key, lowered),
            )
        )
        if not products:
            # Only now pay for the scan (~1.8s on 351k rows): a leading
            # wildcard cannot use an index, but it is the one way to find a
            # medicine by its SECOND ingredient ("...+paracetamol"). Rare
            # enough to be worth the cost; if it ever becomes common, the fix
            # is an ingredient->product join table, not a bigger index.
            products = _catalogue_query(MedicineProduct.composition_key.like(f"%{lowered}%"))
        for p in products:
            if remaining <= 0:
                break
            if p.formulation_key in seen_compositions:
                continue
            seen_compositions.add(p.formulation_key)
            results.append(
                {
                    "drug_id": PRODUCT_ID_PREFIX + p.id,
                    "generic_name": p.drug.generic_name if p.drug else (p.composition or p.name),
                    "composition": p.composition or "composition not listed",
                    "brand_names": [p.name],
                    "matched_brand": p.name,
                    "has_prices": p.price_inr is not None,
                    # False means no contraindication/interaction/pregnancy data
                    # exists for this medicine. The UI must not present it as
                    # checked-and-safe.
                    "has_safety_data": p.drug_id is not None,
                    "prescription_required": p.prescription_required,
                }
            )
            remaining -= 1

    return results
