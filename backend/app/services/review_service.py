"""
Builds the review payload (safety flags + price comparison) for a list of
medicines, whatever their origin.

This exists because screening used to happen only inside the prescription
upload handler, against the medicines OCR had found. Anything the patient
typed in by hand afterwards -- or corrected, or added from a pack scan --
went straight to confirmation unscreened. A manually entered "Zerodol PT" was
therefore never checked against the CDSCO prohibited list, never checked
against a recorded penicillin allergy, and never compared on price. The
patient had no way of knowing the check had not run.

So the whole review step lives here, takes a plain list of names, and both the
upload path and the on-demand /prescriptions/screen endpoint call it. One code
path means a typed medicine and a scanned one get exactly the same scrutiny.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.models import DrugKnowledge
from app.schemas.schemas import ExtractedMedication, SafetyFlagOut
from app.services import price_service
from app.services.ocr_service import ExtractedMed, extract_structured_medications
from app.services.safety_service import screen_prescription


@dataclass
class MedicineInput:
    """One medicine to review. Everything except the name is optional --
    a hand-typed row starts with nothing else."""

    raw_name: str
    matched_drug_id: str | None = None
    dosage: str | None = None
    frequency: str | None = None
    duration_days: int | None = None
    instructions: str | None = None


def resolve(db: Session, item: MedicineInput) -> ExtractedMed:
    """
    Works out what a typed medicine name actually is.

    A name on its own cannot be screened for a banned fixed-dose combination:
    "Zerodol PT" is a brand, and the prohibition is on the three molecules
    inside it. So the name goes through the same matcher the prescription
    scanner uses -- exact catalogue lookup first, then the fuzzy brand index --
    to recover the composition, the curated drug link, and the price
    formulation.
    """
    name = (item.raw_name or "").strip()
    if not name:
        return ExtractedMed(
            raw_name=name,
            matched_drug_id=item.matched_drug_id,
            matched_generic_name=None,
            match_score=None,
            dosage=item.dosage,
            frequency=item.frequency,
            duration_days=item.duration_days,
            instructions=item.instructions,
        )

    product = price_service.find_product_by_name(db, name)
    matched: ExtractedMed | None = None

    if product is None:
        # No exact brand hit: fall back to the fuzzy matcher, which is what
        # reads a smudged prescription line. Passing a single clean name is
        # its easiest possible input.
        candidates = extract_structured_medications(name, db)
        matched = candidates[0] if candidates else None

    drug_id = item.matched_drug_id
    generic = None
    composition = None
    formulation = None
    unit_price = None
    score = None

    if product is not None:
        drug_id = drug_id or product.drug_id
        composition = product.composition
        formulation = product.formulation_key
        unit_price = product.price_per_unit or product.price_inr
        score = 1.0
        if product.drug:
            generic = product.drug.generic_name
        else:
            generic = product.composition
    elif matched is not None:
        drug_id = drug_id or matched.matched_drug_id
        generic = matched.matched_generic_name
        composition = matched.composition
        formulation = matched.formulation_key
        unit_price = matched.catalogue_unit_price
        score = matched.match_score

    if generic is None and drug_id:
        drug = db.query(DrugKnowledge).filter(DrugKnowledge.id == drug_id).first()
        generic = drug.generic_name if drug else None

    return ExtractedMed(
        raw_name=name,
        matched_drug_id=drug_id,
        matched_generic_name=generic,
        match_score=score,
        dosage=item.dosage,
        frequency=item.frequency,
        duration_days=item.duration_days,
        instructions=item.instructions,
        composition=composition,
        formulation_key=formulation,
        catalogue_unit_price=unit_price,
    )


def build_review(
    db: Session,
    patient_id: str,
    extracted: list[ExtractedMed],
) -> tuple[list[ExtractedMedication], list]:
    """
    Screens a resolved list and attaches prices.

    Returns (medications, raw safety results). The second value is handed back
    so callers that also screen free text -- the upload path checks the OCR
    transcript for banned drugs that never became a row -- can avoid
    double-reporting the same flag.

    Screening runs over the WHOLE list at once, not per medicine, because the
    duplicate-therapy and interaction checks only mean anything in context: two
    NSAIDs are each fine alone.
    """
    safety = screen_prescription(
        db,
        patient_id,
        [(e.raw_name, e.matched_drug_id) for e in extracted],
        compositions=[e.composition for e in extracted],
    )

    out: list[ExtractedMedication] = []
    for i, e in enumerate(extracted):
        drug = (
            db.query(DrugKnowledge).filter(DrugKnowledge.id == e.matched_drug_id).first()
            if e.matched_drug_id
            else None
        )
        formulation = e.formulation_key or price_service.formulation_key_for_drug(db, drug)
        options, cheapest = price_service.compare(
            db,
            formulation_key=formulation,
            drug=drug,
            reference_unit_price=e.catalogue_unit_price,
        )

        flags = safety[i].flags if i < len(safety) else []
        out.append(
            ExtractedMedication(
                raw_name=e.raw_name,
                matched_drug_id=e.matched_drug_id,
                matched_generic_name=e.matched_generic_name,
                match_score=e.match_score,
                dosage=e.dosage,
                frequency=e.frequency,
                duration_days=e.duration_days,
                instructions=e.instructions,
                price_options=options,
                cheapest=cheapest,
                safety_flags=[
                    SafetyFlagOut(
                        kind=f.kind,
                        severity=f.severity,
                        title=f.title,
                        detail=f.detail,
                        action=f.action,
                        source=f.source,
                    )
                    for f in flags
                ],
                has_safety_data=e.matched_drug_id is not None,
            )
        )

    return out, safety


def review_names(
    db: Session, patient_id: str, items: list[MedicineInput]
) -> list[ExtractedMedication]:
    """Resolve + screen + price, for medicines that arrived as plain names."""
    return build_review(db, patient_id, [resolve(db, item) for item in items])[0]
