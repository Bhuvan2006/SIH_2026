from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_patient
from app.db.database import get_db
from app.models.models import Allergy, Condition, ConsentRecord, EmergencyContact, Patient, Surgery
from app.schemas.schemas import (
    AllergyIn,
    AllergyOut,
    ConditionIn,
    ConditionOut,
    ConsentIn,
    ConsentOut,
    EmergencyContactIn,
    EmergencyContactOut,
    PatientOut,
    PatientUpdate,
    SurgeryIn,
    SurgeryOut,
)
from app.services.patient_file_service import write_patient_file
from app.services.translation_service import SUPPORTED_LANGUAGES

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("/me", response_model=PatientOut)
def get_me(patient: Patient = Depends(get_current_patient)):
    return patient


@router.patch("/me", response_model=PatientOut)
def update_me(
    payload: PatientUpdate,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    data = payload.model_dump(exclude_unset=True)

    # Language is validated against the supported set rather than trusted.
    lang = data.pop("preferred_language", None)
    if lang is not None and lang in SUPPORTED_LANGUAGES:
        patient.preferred_language = lang

    for field, value in data.items():
        if hasattr(patient, field):
            setattr(patient, field, value)

    db.commit()
    db.refresh(patient)
    write_patient_file(db, patient.id)
    return patient


# ---------- Allergies ----------

@router.get("/me/allergies", response_model=list[AllergyOut])
def list_allergies(patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)):
    return db.query(Allergy).filter(Allergy.patient_id == patient.id).all()


@router.post("/me/allergies", response_model=AllergyOut)
def add_allergy(
    payload: AllergyIn,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    allergy = Allergy(patient_id=patient.id, **payload.model_dump())
    db.add(allergy)
    db.commit()
    db.refresh(allergy)
    write_patient_file(db, patient.id)
    return allergy


@router.delete("/me/allergies/{allergy_id}")
def delete_allergy(
    allergy_id: str,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    allergy = (
        db.query(Allergy).filter(Allergy.id == allergy_id, Allergy.patient_id == patient.id).first()
    )
    if not allergy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Allergy not found")
    db.delete(allergy)
    db.commit()
    write_patient_file(db, patient.id)
    return {"deleted": allergy_id}


# ---------- Surgeries ----------

@router.get("/me/surgeries", response_model=list[SurgeryOut])
def list_surgeries(patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)):
    return (
        db.query(Surgery)
        .filter(Surgery.patient_id == patient.id)
        .order_by(Surgery.year.desc().nullslast())
        .all()
    )


@router.post("/me/surgeries", response_model=SurgeryOut)
def add_surgery(
    payload: SurgeryIn,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    if not payload.name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name the operation.")
    surgery = Surgery(patient_id=patient.id, **{**payload.model_dump(), "name": payload.name.strip()})
    db.add(surgery)
    db.commit()
    db.refresh(surgery)
    write_patient_file(db, patient.id)
    return surgery


@router.delete("/me/surgeries/{surgery_id}")
def delete_surgery(
    surgery_id: str,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    surgery = (
        db.query(Surgery).filter(Surgery.id == surgery_id, Surgery.patient_id == patient.id).first()
    )
    if not surgery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Surgery not found")
    db.delete(surgery)
    db.commit()
    write_patient_file(db, patient.id)
    return {"deleted": surgery_id}


@router.delete("/me/conditions/{condition_id}")
def delete_condition(
    condition_id: str,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    condition = (
        db.query(Condition)
        .filter(Condition.id == condition_id, Condition.patient_id == patient.id)
        .first()
    )
    if not condition:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Condition not found")
    db.delete(condition)
    db.commit()
    write_patient_file(db, patient.id)
    return {"deleted": condition_id}


# ---------- Emergency contacts ----------

@router.get("/me/emergency-contacts", response_model=list[EmergencyContactOut])
def list_emergency_contacts(
    patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)
):
    return (
        db.query(EmergencyContact)
        .filter(EmergencyContact.patient_id == patient.id)
        .order_by(EmergencyContact.is_primary.desc())
        .all()
    )


@router.post("/me/emergency-contacts", response_model=EmergencyContactOut)
def add_emergency_contact(
    payload: EmergencyContactIn,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    contact = EmergencyContact(patient_id=patient.id, **payload.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)
    write_patient_file(db, patient.id)
    return contact


@router.delete("/me/emergency-contacts/{contact_id}")
def delete_emergency_contact(
    contact_id: str,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    contact = (
        db.query(EmergencyContact)
        .filter(EmergencyContact.id == contact_id, EmergencyContact.patient_id == patient.id)
        .first()
    )
    if not contact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    db.delete(contact)
    db.commit()
    write_patient_file(db, patient.id)
    return {"deleted": contact_id}


@router.get("/me/languages")
def list_languages():
    return SUPPORTED_LANGUAGES


# ---------- Consent (DPDP-aligned) ----------

@router.post("/me/consent", response_model=ConsentOut)
def grant_consent(
    payload: ConsentIn,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    record = ConsentRecord(
        patient_id=patient.id,
        consent_type=payload.consent_type,
        purpose_text=payload.purpose_text,
        granted=payload.granted,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/me/consent", response_model=list[ConsentOut])
def list_consents(patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)):
    return (
        db.query(ConsentRecord)
        .filter(ConsentRecord.patient_id == patient.id)
        .order_by(ConsentRecord.created_at.desc())
        .all()
    )


@router.delete("/me/consent/{consent_id}", response_model=ConsentOut)
def withdraw_consent(
    consent_id: str,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    from datetime import datetime

    from fastapi import HTTPException, status

    record = (
        db.query(ConsentRecord)
        .filter(ConsentRecord.id == consent_id, ConsentRecord.patient_id == patient.id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consent record not found")
    record.granted = False
    record.withdrawn_at = datetime.utcnow()
    db.commit()
    db.refresh(record)
    return record


# ---------- Conditions ----------

@router.post("/me/conditions", response_model=ConditionOut)
def add_condition(
    payload: ConditionIn,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    condition = Condition(
        patient_id=patient.id,
        name=payload.name,
        diagnosed_date=payload.diagnosed_date,
        notes=payload.notes,
    )
    db.add(condition)
    db.commit()
    db.refresh(condition)
    write_patient_file(db, patient.id)
    return condition


@router.get("/me/conditions", response_model=list[ConditionOut])
def list_conditions(patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)):
    return db.query(Condition).filter(Condition.patient_id == patient.id).all()
