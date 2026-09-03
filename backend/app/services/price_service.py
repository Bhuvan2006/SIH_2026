"""
Price comparison across the imported Indian medicine catalogue.

Two datasets sit behind this, and they answer different questions:

  * MedicineProduct -- ~246k real Indian branded products with MRP, imported
    from the open Indian-Medicine-Dataset. Wide coverage, real brand names,
    but no clinical data and no live pricing.
  * PriceEntry      -- the small hand-written sample attached to curated
    drugs, including illustrative Jan Aushadhi generic prices.

The catalogue is preferred when a composition is known, because it reflects
what a patient will actually see at a chemist. The curated entries stay as a
fallback so the demo path still works for drugs the catalogue misses.

Savings are quoted against a reference price -- the brand the patient was
actually prescribed -- rather than against the most expensive product sharing
that composition. With 17,000 paracetamol brands the costliest is an outlier,
and "save 96%" measured against an outlier is a number that means nothing.
"""
from __future__ import annotations

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models.models import DrugKnowledge, MedicineProduct
from app.schemas.schemas import PriceOption

DISCLAIMER = (
    "Prices are the manufacturer's printed MRP from an open Indian medicine dataset, "
    "not live pharmacy pricing, and some entries may be out of date. This is informational "
    "only -- it does not facilitate a purchase, and switching brands should always be "
    "confirmed with your doctor or pharmacist first (composition and dose matter, but so "
    "can inactive ingredients and individual response). The source dataset records only "
    "two active ingredients per product, so a medicine listed here may contain a third one "
    "we cannot see -- always check the pack's own ingredient list before switching."
)

MAX_OPTIONS = 8


def _option_from_product(p: MedicineProduct) -> PriceOption:
    return PriceOption(
        product_name=p.name,
        manufacturer=p.manufacturer,
        is_generic=bool(p.is_generic),
        price_inr=round(p.price_inr, 2),
        unit=p.pack_size_label or "per pack",
        prescription_required=p.prescription_required,
    )


def _unit_price(p: MedicineProduct) -> float | None:
    """What one dose costs. Falls back to the pack price for volume packs
    (syrups, injections) where there is no dose count to divide by."""
    return p.price_per_unit if p.price_per_unit is not None else p.price_inr


def _apply_savings(options: list[PriceOption], reference_price: float | None) -> None:
    """
    Fills savings_pct_vs_costliest in place. Despite the field name the
    baseline is the reference price when one is known (see module docstring);
    it falls back to the dearest option shown so the field is never blank.
    """
    baseline = reference_price or max((o.price_inr for o in options), default=0.0)
    if not baseline:
        return
    for o in options:
        o.savings_pct_vs_costliest = round(max(0.0, (1 - o.price_inr / baseline)) * 100, 1)


def _apply_savings_per_unit(
    options: list[PriceOption],
    unit_prices: list[float | None],
    reference_unit_price: float | None,
) -> None:
    """
    Same idea as _apply_savings, but the percentage compares cost per dose. A
    saving computed from pack prices is wrong whenever the packs differ in
    size, which is most of the time.
    """
    usable = [u for u in unit_prices if u]
    baseline = reference_unit_price or (max(usable) if usable else 0.0)
    if not baseline:
        return
    for o, unit in zip(options, unit_prices):
        if not unit:
            continue
        o.savings_pct_vs_costliest = round(max(0.0, (1 - unit / baseline)) * 100, 1)


def options_for_formulation(
    db: Session,
    formulation_key: str | None,
    reference_unit_price: float | None = None,
    limit: int = MAX_OPTIONS,
) -> list[PriceOption]:
    """
    Cheapest interchangeable products: same molecules, same strengths, same
    dosage form. Sorted by price per dose, not per pack, so a strip of 15 is
    not penalised for being bigger than a strip of 10.
    """
    if not formulation_key:
        return []

    rows = (
        db.query(MedicineProduct)
        .filter(
            MedicineProduct.formulation_key == formulation_key,
            MedicineProduct.is_discontinued.is_(False),
            MedicineProduct.price_inr.isnot(None),
            MedicineProduct.price_inr > 0,
        )
        .order_by(MedicineProduct.price_per_unit.asc(), MedicineProduct.price_inr.asc())
        .limit(limit)
        .all()
    )
    options = [_option_from_product(p) for p in rows]
    _apply_savings_per_unit(options, [_unit_price(p) for p in rows], reference_unit_price)
    return options


def options_for_curated_drug(drug: DrugKnowledge | None) -> list[PriceOption]:
    """The original hand-written sample prices, used when the catalogue has nothing."""
    if not drug or not drug.price_entries:
        return []
    options = [
        PriceOption(
            product_name=e.product_name,
            manufacturer=e.manufacturer,
            is_generic=e.is_generic,
            price_inr=e.price_inr,
            unit=e.unit,
        )
        for e in drug.price_entries
    ]
    options.sort(key=lambda o: o.price_inr)
    _apply_savings(options, None)
    return options


def compare(
    db: Session,
    formulation_key: str | None = None,
    drug: DrugKnowledge | None = None,
    reference_unit_price: float | None = None,
    limit: int = MAX_OPTIONS,
) -> tuple[list[PriceOption], PriceOption | None]:
    """
    Returns (options sorted cheapest-first, cheapest). Catalogue first, curated
    sample as fallback.

    Only genuinely interchangeable products are compared -- see
    options_for_formulation. Nothing here widens the search to "same molecule,
    any strength" if that finds too few results: a shorter honest list beats a
    longer one that invites the patient to swap 650mg tablets for 500mg syrup.
    """
    options = options_for_formulation(db, formulation_key, reference_unit_price, limit)
    if not options:
        options = options_for_curated_drug(drug)
    return options, (options[0] if options else None)


def formulation_key_for_drug(db: Session, drug: DrugKnowledge | None) -> str | None:
    """
    Finds a catalogue formulation for a curated drug, via the products linked
    to it at import time. Picks the most common one, which for a drug like
    paracetamol means the strength and form most Indians are actually sold.

    This is a fallback for when we only know the generic name -- when the
    prescription or pack named a specific brand, use that product's own
    formulation_key instead, since it reflects the strength actually
    prescribed.
    """
    if not drug:
        return None
    keys: dict[str, int] = {}
    for (key,) in (
        db.query(MedicineProduct.formulation_key)
        .filter(MedicineProduct.drug_id == drug.id, MedicineProduct.formulation_key.isnot(None))
        .all()
    ):
        keys[key] = keys.get(key, 0) + 1
    if not keys:
        return None

    # Prefer an oral solid form. Doxycycline's single commonest formulation in
    # the catalogue is an IV injection, so a prescription reading "Doxycycline
    # 100mg Tablet" was being priced against a Rs374 vial. When the patient is
    # taking tablets, tablets are the honest comparison.
    oral = {k: n for k, n in keys.items() if k.endswith(("|tablet", "|capsule"))}
    return max((oral or keys).items(), key=lambda kv: kv[1])[0]


def find_product_by_name(db: Session, name: str | None) -> MedicineProduct | None:
    """
    Looks up a scanned or typed brand name in the catalogue. Exact match on the
    lowercased name first, then a prefix match, which covers the common case
    where a pack reads "Dolo 650" but the catalogue row is "Dolo 650 Tablet".
    """
    if not name or not name.strip():
        return None
    key = " ".join(name.strip().lower().split())

    exact = (
        db.query(MedicineProduct)
        .filter(MedicineProduct.name_key == key, MedicineProduct.is_discontinued.is_(False))
        .order_by(MedicineProduct.price_inr.asc())
        .first()
    )
    if exact:
        return exact

    # Range predicate rather than LIKE 'key%': SQLite will not use the
    # name_key index for a LIKE prefix (its LIKE is case-insensitive), which
    # turns every pack scan into a full table scan.
    return (
        db.query(MedicineProduct)
        .filter(
            and_(MedicineProduct.name_key >= key, MedicineProduct.name_key < key + "￿"),
            MedicineProduct.is_discontinued.is_(False),
        )
        .order_by(MedicineProduct.price_inr.asc())
        .first()
    )
