import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import get_current_patient
from app.db.database import get_db
from app.models.models import (
    ConfirmationStatus,
    DrugKnowledge,
    Medication,
    Patient,
    Prescription,
    Schedule,
)
from app.services.patient_file_service import write_patient_file
from app.services import price_service, review_service
from app.services.safety_service import screen_prescription, screen_raw_text_for_banned
from app.schemas.schemas import (
    ExtractedMedication,
    MedicationOut,
    MedicineScreenRequest,
    MedicineScreenResponse,
    PrescriptionConfirmRequest,
    PrescriptionOut,
    PrescriptionUploadResponse,
    PriceOption,
    SafetyFlagOut,
)
from app.services.ocr_service import (
    identify_medicine_from_pack,
    OCRResult,
    OCRUnavailableError,
    extract_structured_medications,
    extract_via_gemini_vision,
    get_ocr_provider,
)

logger = logging.getLogger("arogya.prescriptions")

router = APIRouter(prefix="/prescriptions", tags=["prescriptions"])
settings = get_settings()

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploaded_files"
UPLOAD_DIR.mkdir(exist_ok=True)


@router.post("/upload", response_model=PrescriptionUploadResponse)
async def upload_prescription(
    file: UploadFile = File(...),
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg", "image/webp"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{file.content_type}'. Upload a JPEG, PNG, or WEBP image.",
        )

    ext = Path(file.filename or "upload.png").suffix or ".png"
    saved_name = f"{uuid.uuid4()}{ext}"
    saved_path = UPLOAD_DIR / saved_name
    with saved_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    ocr_provider = get_ocr_provider()
    ocr_unavailable = False
    try:
        ocr_result = ocr_provider.extract(str(saved_path))
    except OCRUnavailableError as exc:
        # Local OCR can't run (Tesseract missing, or Gemini-only mode). Don't
        # fail the upload: the image is already saved, and the patient must
        # review and confirm every field by hand regardless (build plan
        # §0.1), so we degrade rather than returning a 500.
        logger.warning("Local OCR unavailable (%s); will try Gemini vision if enabled.", exc)
        ocr_unavailable = True
        ocr_result = OCRResult(raw_text="", provider="unavailable")

    extracted = extract_structured_medications(ocr_result.raw_text, db) if not ocr_unavailable else []

    # --- Gemini vision fallback ------------------------------------------
    # Tesseract is good at clean printed text and poor at handwriting, which
    # is exactly the case build plan §0.1 flags as hard. When Tesseract is
    # missing, unreadable, or found no known medicine, a vision model gets a
    # second pass. The result is still OCR output: it goes to the same
    # mandatory confirmation screen and never auto-confirms.
    used_vision_fallback = False
    if settings.OCR_PROVIDER in ("auto", "gemini") and (ocr_unavailable or not extracted):
        try:
            vision_result, vision_meds = extract_via_gemini_vision(str(saved_path), db)
            if vision_meds or vision_result.raw_text:
                ocr_result = vision_result
                extracted = vision_meds
                ocr_unavailable = False
                used_vision_fallback = True
                logger.info("Gemini vision extracted %d medicine(s) from the image.", len(vision_meds))
        except OCRUnavailableError as exc:
            logger.warning("Gemini vision fallback unavailable: %s", exc)

    # Heuristic: very short recognized text relative to a typical
    # prescription, or low average per-word confidence, suggests
    # handwriting or a poor-quality image -- route to manual review
    # rather than silently trusting a thin OCR result. See §0.1 of the
    # build plan: this is the single most important safety gate in the
    # OCR pipeline.
    is_handwritten_guess = ocr_result.avg_confidence < settings.OCR_LOW_CONFIDENCE_THRESHOLD or len(
        ocr_result.words
    ) < 3

    confirmation_status = (
        ConfirmationStatus.NEEDS_REVIEW if is_handwritten_guess or not extracted else ConfirmationStatus.NEEDS_REVIEW
    )
    # Note: confirmation_status is ALWAYS needs_review at this stage --
    # nothing becomes "confirmed" until the patient explicitly reviews and
    # calls the /confirm endpoint. There is intentionally no auto-confirm
    # path, even for high-confidence OCR.

    prescription = Prescription(
        patient_id=patient.id,
        file_path=str(saved_path),
        ocr_raw_text=ocr_result.raw_text,
        ocr_confidence=ocr_result.avg_confidence,
        ocr_provider=ocr_result.provider,
        is_handwritten_guess=is_handwritten_guess,
        confirmation_status=confirmation_status,
    )
    db.add(prescription)
    db.commit()
    db.refresh(prescription)

    if ocr_unavailable:
        review_message = (
            "Automatic scanning is unavailable on this server, so nothing could be read from the "
            "image. Your prescription photo has been saved -- please add each medicine manually "
            "below before confirming."
        )
    elif used_vision_fallback:
        review_message = (
            "This was read by our AI image reader, which handles handwriting better but can still "
            "misread a name or dose. Please check every field below against the original "
            "prescription carefully before confirming."
        )
    elif is_handwritten_guess or not extracted:
        review_message = (
            "We couldn't read this confidently -- it may be handwritten or the photo quality is low. "
            "Please check every field carefully below, or add medicines manually, before confirming."
        )
    else:
        review_message = (
            "Please review each extracted medicine carefully and correct anything that's wrong before confirming."
        )

    # --- Inline price comparison + safety screening -----------------------
    # Both are computed here, at review time, rather than on a later screen:
    # the moment to notice "this clashes with your penicillin allergy" or
    # "there is a ₹9 generic of this" is while the patient is still deciding,
    # not after reminders are scheduled.
    medications_out, safety_by_index = review_service.build_review(db, patient.id, extracted)

    # Catch banned drugs present in the transcription that never became an
    # extracted medicine (not in our knowledge base -- common for withdrawn
    # molecules), so they still reach the patient.
    raw_flags = screen_raw_text_for_banned(ocr_result.raw_text, safety_by_index)

    return PrescriptionUploadResponse(
        prescription_id=prescription.id,
        ocr_confidence=round(ocr_result.avg_confidence, 2),
        is_handwritten_guess=is_handwritten_guess,
        confirmation_status=prescription.confirmation_status.value,
        ocr_raw_text=ocr_result.raw_text,
        extracted_medications=medications_out,
        review_message=review_message,
        prescription_flags=[
            SafetyFlagOut(
                kind=f.kind, severity=f.severity, title=f.title,
                detail=f.detail, action=f.action, source=f.source,
            )
            for f in raw_flags
        ],
    )


@router.post("/identify-medicine")
async def identify_medicine(
    file: UploadFile = File(...),
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    """
    Reads a photo of a medicine PACK (strip / bottle / carton) and returns the
    printed details, a match against the drug database, safety flags for this
    patient, and price alternatives.

    The fallback for an unreadable prescription: the pack in the patient's
    hand is usually far more legible than handwriting, and prints the
    composition. Nothing is saved here -- the patient still reviews and
    confirms, exactly as with prescription OCR.
    """
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg", "image/webp"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{file.content_type}'. Use a JPEG, PNG or WEBP photo.",
        )

    ext = Path(file.filename or "pack.jpg").suffix or ".jpg"
    saved_path = UPLOAD_DIR / f"pack-{uuid.uuid4()}{ext}"
    with saved_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        result = identify_medicine_from_pack(str(saved_path), db)
    except OCRUnavailableError as exc:
        logger.warning("Medicine pack reading unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Reading medicine photos isn't available right now. You can still type the "
                "medicine name in manually."
            ),
        ) from exc

    if not result["is_medicine_pack"]:
        return {
            **result,
            "safety_flags": [],
            "price_options": [],
            "cheapest": None,
            "message": (
                "That doesn't look like a medicine package. Try a photo of the strip, bottle or "
                "carton with the printed name facing the camera."
            ),
        }

    # Same five-check screening a prescribed medicine gets, so scanning a pack
    # is not a way to bypass the allergy/pregnancy/banned-drug checks.
    name_for_screen = result["brand_name"] or result["composition"] or ""
    screened = screen_prescription(
        db,
        patient.id,
        [(name_for_screen, result["matched_drug_id"])],
        compositions=[result.get("composition")],
    )
    flags = screened[0].flags if screened else []

    # A scanned pack usually gives us a brand name we can look up directly in
    # the catalogue, which is both a better composition and a real MRP to
    # price against.
    pack_product = price_service.find_product_by_name(db, result.get("brand_name"))
    drug = (
        db.query(DrugKnowledge).filter(DrugKnowledge.id == result["matched_drug_id"]).first()
        if result["matched_drug_id"]
        else None
    )
    formulation = (
        (pack_product.formulation_key if pack_product else None)
        or price_service.formulation_key_for_drug(db, drug)
    )
    options, cheapest = price_service.compare(
        db,
        formulation_key=formulation,
        drug=drug,
        reference_unit_price=(
            (pack_product.price_per_unit or pack_product.price_inr) if pack_product else None
        ),
    )

    if result["confidence"] < 0.5:
        message = (
            "We could only partly read that pack. Check every field below, and retake the photo "
            "in better light if the name looks wrong."
        )
    elif not result["matched_drug_id"] and pack_product is not None:
        # Found in the bulk catalogue but not in the curated set: we can price
        # it, we cannot clinically clear it, and saying so plainly matters more
        # than looking capable.
        message = (
            "We found this medicine in our price list, but it isn't in our clinical database yet, "
            "so we could not check it against your allergies or conditions. Please confirm the "
            "details with your pharmacist."
        )
    elif not result["matched_drug_id"]:
        message = (
            "We read the pack but this medicine isn't in our database yet, so we can't check it "
            "against your allergies or show prices. Please confirm the details yourself."
        )
    else:
        message = "Check these details against the pack before adding the medicine."

    return {
        **result,
        "safety_flags": [
            SafetyFlagOut(
                kind=f.kind, severity=f.severity, title=f.title,
                detail=f.detail, action=f.action, source=f.source,
            )
            for f in flags
        ],
        "price_options": options,
        "cheapest": cheapest,
        "message": message,
    }


@router.post("/screen", response_model=MedicineScreenResponse)
def screen_medications(
    payload: MedicineScreenRequest,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    """
    Runs the full safety check and price comparison over whatever the patient
    currently has in the review table.

    Screening used to be tied to the upload response, so it only ever covered
    what OCR read from the image. A medicine typed in by hand, corrected after
    a misread, or added from a pack scan reached confirmation with no check at
    all -- and nothing on screen said so. This endpoint takes the live list, so
    every row is screened whatever its origin.

    A name alone is not enough to match a banned fixed-dose combination, so
    each name is resolved against the medicine catalogue first to recover its
    composition (see review_service.resolve).
    """
    items = [
        review_service.MedicineInput(
            raw_name=m.raw_name,
            matched_drug_id=m.matched_drug_id,
            dosage=m.dosage,
            frequency=m.frequency,
            duration_days=m.duration_days,
            instructions=m.instructions,
        )
        for m in payload.medications
        if (m.raw_name or "").strip()
    ]
    medications = review_service.review_names(db, patient.id, items)
    has_critical = any(
        flag.severity == "critical" for med in medications for flag in med.safety_flags
    )
    return MedicineScreenResponse(medications=medications, has_critical=has_critical)


@router.post("/{prescription_id}/confirm", response_model=PrescriptionOut)
def confirm_prescription(
    prescription_id: str,
    payload: PrescriptionConfirmRequest,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    prescription = (
        db.query(Prescription)
        .filter(Prescription.id == prescription_id, Prescription.patient_id == patient.id)
        .first()
    )
    if not prescription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prescription not found")

    if not payload.medications:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one medication is required")

    from datetime import datetime

    prescription.doctor_name = payload.doctor_name
    prescription.confirmation_status = ConfirmationStatus.CONFIRMED
    prescription.confirmed_at = datetime.utcnow()

    for med_in in payload.medications:
        medication = Medication(
            prescription_id=prescription.id,
            patient_id=patient.id,
            raw_name=med_in.raw_name,
            matched_drug_id=med_in.matched_drug_id,
            dosage=med_in.dosage,
            frequency=med_in.frequency,
            duration_days=med_in.duration_days,
            route=med_in.route,
            instructions=med_in.instructions,
            is_confirmed=True,
        )
        db.add(medication)
        db.flush()

        for t in med_in.reminder_times:
            db.add(Schedule(medication_id=medication.id, time_of_day=t))

    db.commit()
    db.refresh(prescription)

    # Refresh the patient's data file so the chatbot can answer questions
    # about these medicines right away (see patient_file_service).
    write_patient_file(db, patient.id)

    return prescription


def _medication_out(db: Session, med: Medication) -> MedicationOut:
    """Medication enriched with its schedule and canonical drug details."""
    times = [
        s.time_of_day
        for s in db.query(Schedule)
        .filter(Schedule.medication_id == med.id, Schedule.active == True)  # noqa: E712
        .all()
    ]
    storage = drug_class = generic = None
    if med.matched_drug_id:
        drug = db.query(DrugKnowledge).filter(DrugKnowledge.id == med.matched_drug_id).first()
        if drug:
            storage = drug.storage_instructions
            drug_class = drug.drug_class
            generic = drug.generic_name

    return MedicationOut(
        id=med.id,
        raw_name=med.raw_name,
        matched_drug_id=med.matched_drug_id,
        dosage=med.dosage,
        frequency=med.frequency,
        duration_days=med.duration_days,
        route=med.route,
        instructions=med.instructions,
        is_confirmed=med.is_confirmed,
        matched_generic_name=generic,
        reminder_times=sorted(times),
        storage_note=storage,
        drug_class=drug_class,
    )


def _prescription_out(db: Session, p: Prescription) -> PrescriptionOut:
    return PrescriptionOut(
        id=p.id,
        uploaded_at=p.uploaded_at,
        doctor_name=p.doctor_name,
        confirmation_status=p.confirmation_status.value if p.confirmation_status else "pending",
        ocr_confidence=p.ocr_confidence,
        is_handwritten_guess=p.is_handwritten_guess,
        medications=[_medication_out(db, m) for m in p.medications],
    )


@router.get("", response_model=list[PrescriptionOut])
def list_prescriptions(patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)):
    rows = (
        db.query(Prescription)
        .filter(Prescription.patient_id == patient.id)
        .order_by(Prescription.uploaded_at.desc())
        .all()
    )
    return [_prescription_out(db, p) for p in rows]


@router.delete("/{prescription_id}")
def delete_prescription(
    prescription_id: str,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    """
    Removes a prescription and everything derived from it.

    Needed because an abandoned scan currently sticks around forever as an
    empty "needs review" card with no way to clear it.
    """
    prescription = (
        db.query(Prescription)
        .filter(Prescription.id == prescription_id, Prescription.patient_id == patient.id)
        .first()
    )
    if not prescription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prescription not found")
    db.delete(prescription)
    db.commit()
    write_patient_file(db, patient.id)
    return {"deleted": prescription_id}


@router.get("/{prescription_id}", response_model=PrescriptionOut)
def get_prescription(
    prescription_id: str,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    prescription = (
        db.query(Prescription)
        .filter(Prescription.id == prescription_id, Prescription.patient_id == patient.id)
        .first()
    )
    if not prescription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prescription not found")
    return prescription
