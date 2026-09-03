"""
Emergency medical profile + QR code.

The QR encodes a URL to a PUBLIC page (`/emergency/{token}`) so that a first
responder, ER nurse, or bystander can scan it from a locked phone, a printed
card, or a wristband without logging in -- authentication would defeat the
entire purpose at the moment it matters.

Privacy trade-off, stated plainly: anyone holding the token can read that
profile. It is mitigated by (a) a 32-byte URL-safe random token that cannot
be enumerated, (b) the patient choosing what goes on it, and (c) a regenerate
endpoint that instantly invalidates every previously printed QR code. It is
NOT protected against someone who photographs the QR. Patients should be told
that before printing one.
"""
import base64
import io

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import get_current_patient
from app.db.database import get_db
from app.models.models import (
    Allergy,
    Condition,
    DrugKnowledge,
    EmergencyContact,
    Medication,
    Surgery,
    Patient,
    gen_emergency_token,
)
from app.services.patient_file_service import write_patient_file

router = APIRouter(prefix="/emergency", tags=["emergency"])

# Drug classes that change how a patient is treated in an emergency. These get
# surfaced as explicit red-flag alerts rather than buried in the medicine list:
# a bleeding patient on an anticoagulant, or a collapsed diabetic on insulin,
# is a materially different clinical situation.
CRITICAL_CLASS_KEYWORDS = {
    "anticoagulant": "On blood thinners — bleeding risk, check before any procedure",
    "antiplatelet": "On antiplatelet therapy — increased bleeding risk",
    "insulin": "On insulin — consider hypoglycaemia if unconscious or confused",
    "antidiabetic": "On diabetes medication — consider hypoglycaemia",
    "biguanide": "On metformin — risk of lactic acidosis; pause before contrast imaging",
    "beta": "On beta-blockers — may mask tachycardia and hypoglycaemia symptoms",
    "corticosteroid": "On steroids — do not stop abruptly; adrenal crisis risk",
    "immunosupp": "Immunosuppressed — higher infection risk",
}


def _critical_alerts(db: Session, patient_id: str) -> list[str]:
    alerts: list[str] = []

    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if patient and patient.is_pregnant:
        due = f" (due {patient.pregnancy_due_date})" if patient.pregnancy_due_date else ""
        alerts.append(f"PREGNANT{due} — avoid contraindicated drugs and imaging radiation")


    for allergy in db.query(Allergy).filter(Allergy.patient_id == patient_id).all():
        severity = (allergy.severity or "").lower()
        if severity in ("severe", "anaphylaxis"):
            reaction = f" ({allergy.reaction})" if allergy.reaction else ""
            alerts.append(f"SEVERE ALLERGY: {allergy.allergen}{reaction} — do not administer")

    meds = (
        db.query(Medication)
        .filter(Medication.patient_id == patient_id, Medication.is_confirmed == True)  # noqa: E712
        .all()
    )
    seen: set[str] = set()
    for med in meds:
        if not med.matched_drug_id:
            continue
        drug = db.query(DrugKnowledge).filter(DrugKnowledge.id == med.matched_drug_id).first()
        if not drug or not drug.drug_class:
            continue
        klass = drug.drug_class.lower()
        for keyword, message in CRITICAL_CLASS_KEYWORDS.items():
            if keyword in klass and message not in seen:
                seen.add(message)
                alerts.append(message)

    return alerts


def _public_profile(db: Session, patient: Patient) -> dict:
    allergies = db.query(Allergy).filter(Allergy.patient_id == patient.id).all()
    conditions = db.query(Condition).filter(Condition.patient_id == patient.id).all()
    contacts = (
        db.query(EmergencyContact)
        .filter(EmergencyContact.patient_id == patient.id)
        .order_by(EmergencyContact.is_primary.desc())
        .all()
    )
    meds = (
        db.query(Medication)
        .filter(Medication.patient_id == patient.id, Medication.is_confirmed == True)  # noqa: E712
        .all()
    )

    return {
        "name": patient.name,
        "phone": patient.phone,
        "date_of_birth": patient.date_of_birth,
        "gender": patient.gender,
        "blood_group": patient.blood_group,
        "height_cm": patient.height_cm,
        "weight_kg": patient.weight_kg,
        "organ_donor": patient.organ_donor,
        "implants_devices": patient.implants_devices,
        "emergency_notes": patient.emergency_notes,
        "address": patient.address,
        "primary_doctor": {
            "name": patient.primary_doctor_name,
            "phone": patient.primary_doctor_phone,
        },
        "insurance": {
            "provider": patient.insurance_provider,
            "policy_no": patient.insurance_policy_no,
        },
        "critical_alerts": _critical_alerts(db, patient.id),
        "is_pregnant": patient.is_pregnant,
        "surgeries": [
            {"name": s.name, "year": s.year}
            for s in db.query(Surgery).filter(Surgery.patient_id == patient.id).all()
        ],
        "allergies": [
            {
                "allergen": a.allergen,
                "reaction": a.reaction,
                "severity": a.severity,
            }
            for a in allergies
        ],
        "conditions": [{"name": c.name, "notes": c.notes} for c in conditions],
        "emergency_contacts": [
            {
                "name": c.name,
                "relationship": c.relationship_to_patient,
                "phone": c.phone,
                "is_primary": c.is_primary,
            }
            for c in contacts
        ],
        "medications": [
            {
                "name": m.matched_drug.generic_name if m.matched_drug else m.raw_name,
                "dosage": m.dosage,
                "frequency": m.frequency,
            }
            for m in meds
        ],
    }


@router.get("/qr")
def get_emergency_qr(
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    """
    Returns the emergency URL plus a PNG QR code (base64 data URI) the
    frontend can render or the patient can print.
    """
    settings = get_settings()

    if not patient.emergency_token:
        patient.emergency_token = gen_emergency_token()
        db.commit()

    url = f"{settings.PUBLIC_APP_URL.rstrip('/')}/emergency/{patient.emergency_token}"

    try:
        import qrcode  # type: ignore
    except ImportError:
        # Without the library we can still hand back the URL so the UI can
        # render the QR client-side or just show a link.
        return {"url": url, "qr_data_uri": None, "detail": "qrcode package not installed"}

    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return {"url": url, "qr_data_uri": f"data:image/png;base64,{encoded}"}


@router.post("/qr/regenerate")
def regenerate_emergency_token(
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    """Invalidates every previously shared/printed QR code for this patient."""
    patient.emergency_token = gen_emergency_token()
    db.commit()
    write_patient_file(db, patient.id)
    return {"status": "regenerated", "emergency_token": patient.emergency_token}


@router.get("/me")
def my_emergency_profile(
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    """Authenticated preview of exactly what a scanner would see."""
    return _public_profile(db, patient)


@router.get("/{token}")
def public_emergency_profile(token: str, db: Session = Depends(get_db)):
    """
    PUBLIC — no authentication. This is what the QR code resolves to.
    Only ever addressable with the full random token.
    """
    patient = db.query(Patient).filter(Patient.emergency_token == token).first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This emergency profile link is not valid or has been revoked.",
        )
    return _public_profile(db, patient)
