"""
Doctor-facing API: profile, clinic hours, diary, and patient records.

The access rule that matters
----------------------------
`GET /doctor/patients/{id}` previously had no check whatsoever. Anyone who
registered as a doctor -- registration is an OTP on any phone number -- could
read every patient's name, phone, allergies, conditions and medicines. That is
now gated on there being an appointment between the two, which is the only
thing in this system that makes the access defensible.
"""
from datetime import date as date_cls
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.security import get_current_doctor
from app.db.database import get_db
from app.models.models import (
    Allergy,
    Appointment,
    Condition,
    Doctor,
    DoctorAvailability,
    DoctorTimeOff,
    Medication,
    Patient,
    PatientRecordEdit,
    Surgery,
)
from app.schemas.schemas import (
    AllergyIn,
    AllergyOut,
    ConditionIn,
    AppointmentOut,
    AppointmentUpdate,
    AvailabilityIn,
    AvailabilityOut,
    ConditionOut,
    DaySlotsOut,
    DoctorAppointmentIn,
    DoctorOut,
    DoctorPatientUpdate,
    DoctorUpdate,
    PatientOut,
    PatientSummaryOut,
    RecordEditOut,
    SurgeryIn,
    TimeOffIn,
    TimeOffOut,
)
from app.services import appointment_service as sched
from app.services import patient_summary_service
from app.services.patient_file_service import write_patient_file

router = APIRouter(prefix="/doctor", tags=["doctor"])

VALID_STATUS_TRANSITIONS = {
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"completed", "cancelled"},
    "cancelled": set(),
    "completed": set(),
}


def _serialise(appointment: Appointment, *, with_patient=True) -> AppointmentOut:
    out = AppointmentOut.model_validate(appointment)
    out.time_slot_label = sched.format_slot(appointment.time_slot)
    try:
        at = datetime.combine(
            sched.parse_date(appointment.date), sched.parse_time(appointment.time_slot)
        )
        out.is_past = at < datetime.now()
    except sched.SchedulingError:
        out.is_past = False
    out.doctor = None
    if not with_patient:
        out.patient = None
    return out


# ---------------------------------------------------------------- profile ---

@router.get("/me", response_model=DoctorOut)
def get_me(doctor: Doctor = Depends(get_current_doctor)):
    return doctor


@router.patch("/me", response_model=DoctorOut)
def update_me(
    payload: DoctorUpdate,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    for field, value in payload.model_dump(exclude_unset=True).items():
        if hasattr(doctor, field):
            setattr(doctor, field, value)
    # A doctor only becomes visible to patients once there is a name and a
    # specialisation to show them.
    doctor.profile_completed = bool(doctor.name and doctor.specialization)
    db.commit()
    db.refresh(doctor)
    return doctor


# ----------------------------------------------------------- clinic hours ---

@router.get("/availability", response_model=list[AvailabilityOut])
def list_availability(
    doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)
):
    sched.ensure_default_availability(db, doctor)
    return (
        db.query(DoctorAvailability)
        .filter(DoctorAvailability.doctor_id == doctor.id)
        .order_by(DoctorAvailability.weekday, DoctorAvailability.start_time)
        .all()
    )


@router.post("/availability", response_model=AvailabilityOut, status_code=status.HTTP_201_CREATED)
def add_availability(
    payload: AvailabilityIn,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    try:
        start = sched.parse_time(payload.start_time)
        end = sched.parse_time(payload.end_time)
    except sched.SchedulingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The session has to end after it starts.",
        )

    row = DoctorAvailability(doctor_id=doctor.id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/availability/{availability_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_availability(
    availability_id: str,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    row = (
        db.query(DoctorAvailability)
        .filter(DoctorAvailability.id == availability_id, DoctorAvailability.doctor_id == doctor.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    db.delete(row)
    db.commit()


@router.get("/time-off", response_model=list[TimeOffOut])
def list_time_off(doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    return (
        db.query(DoctorTimeOff)
        .filter(DoctorTimeOff.doctor_id == doctor.id, DoctorTimeOff.date >= date_cls.today().isoformat())
        .order_by(DoctorTimeOff.date)
        .all()
    )


@router.post("/time-off", response_model=TimeOffOut, status_code=status.HTTP_201_CREATED)
def add_time_off(
    payload: TimeOffIn,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    try:
        on = sched.parse_date(payload.date)
    except sched.SchedulingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    clashing = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == doctor.id,
            Appointment.date == on.isoformat(),
            Appointment.status.in_(sched.ACTIVE_STATUSES),
        )
        .count()
    )
    if clashing:
        # Blocking the day silently would strand patients who already hold a
        # slot, so say what needs doing rather than quietly double-booking.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"You have {clashing} appointment(s) booked that day. "
                "Cancel or move them first, then block the date."
            ),
        )

    existing = (
        db.query(DoctorTimeOff)
        .filter(DoctorTimeOff.doctor_id == doctor.id, DoctorTimeOff.date == on.isoformat())
        .first()
    )
    if existing:
        return existing

    row = DoctorTimeOff(doctor_id=doctor.id, date=on.isoformat(), reason=payload.reason)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/time-off/{time_off_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_time_off(
    time_off_id: str,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    row = (
        db.query(DoctorTimeOff)
        .filter(DoctorTimeOff.id == time_off_id, DoctorTimeOff.doctor_id == doctor.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    db.delete(row)
    db.commit()


@router.get("/slots", response_model=DaySlotsOut)
def my_slots(
    date: str,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """The doctor's own view of a day, for scheduling a patient into a gap."""
    try:
        on = sched.parse_date(date)
    except sched.SchedulingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return sched.day_view(db, doctor, on)


# ----------------------------------------------------------------- diary ---

@router.get("/appointments", response_model=list[AppointmentOut])
def list_appointments(
    date: str | None = None,
    upcoming: bool = False,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Appointment)
        .options(joinedload(Appointment.patient))
        .filter(Appointment.doctor_id == doctor.id)
    )
    if date:
        query = query.filter(Appointment.date == date)
    elif upcoming:
        query = query.filter(
            Appointment.date >= date_cls.today().isoformat(),
            Appointment.status.in_(sched.ACTIVE_STATUSES),
        )
    appointments = query.order_by(Appointment.date, Appointment.time_slot).all()
    return [_serialise(a) for a in appointments]


@router.post("/appointments", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
def schedule_appointment(
    payload: DoctorAppointmentIn,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """
    The doctor books a patient in -- a follow-up agreed in the consulting
    room, say. Starts CONFIRMED rather than pending: the doctor scheduling it
    is the confirmation, and asking them to then approve their own booking
    would be theatre.

    Only patients this doctor already has an appointment with can be
    scheduled, so this cannot be used to attach a doctor to an arbitrary
    patient record and unlock it.
    """
    patient = db.query(Patient).filter(Patient.id == payload.patient_id).first()
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    if not sched.doctor_treats_patient(db, doctor.id, patient.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You can only schedule follow-ups for patients who have already "
                "booked with you."
            ),
        )

    try:
        # A doctor writing up their own diary may legitimately record a slot
        # earlier today (the patient walked in at 9, it is now 11).
        sched.validate_booking(
            db, doctor, payload.date, payload.time_slot, allow_same_day_past=True
        )
    except sched.SchedulingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    appointment = Appointment(
        patient_id=patient.id,
        doctor_id=doctor.id,
        date=payload.date,
        time_slot=payload.time_slot,
        notes=payload.notes,
        status="confirmed",
        created_by="doctor",
    )
    db.add(appointment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That slot was taken a moment ago.",
        ) from None
    db.refresh(appointment)
    return _serialise(appointment)


@router.patch("/appointments/{appointment_id}", response_model=AppointmentOut)
def update_appointment(
    appointment_id: str,
    payload: AppointmentUpdate,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    appointment = (
        db.query(Appointment)
        .options(joinedload(Appointment.patient))
        .filter(Appointment.id == appointment_id, Appointment.doctor_id == doctor.id)
        .first()
    )
    if not appointment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

    if payload.status is not None:
        allowed = VALID_STATUS_TRANSITIONS.get(appointment.status, set())
        if payload.status != appointment.status and payload.status not in allowed:
            # Without this a cancelled appointment could be flipped back to
            # confirmed, silently re-booking a slot the patient was told was
            # free.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"An appointment that is {appointment.status} cannot become "
                    f"{payload.status}."
                ),
            )
        appointment.status = payload.status
        if payload.status == "cancelled":
            appointment.cancelled_by = "doctor"

    if payload.doctor_notes is not None:
        appointment.doctor_notes = payload.doctor_notes

    db.commit()
    db.refresh(appointment)
    return _serialise(appointment)


# --------------------------------------------------------------- patients ---

@router.get("/patients")
def list_my_patients(
    doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)
):
    """Patients this doctor has seen or is due to see."""
    rows = (
        db.query(Appointment)
        .options(joinedload(Appointment.patient))
        .filter(Appointment.doctor_id == doctor.id)
        .order_by(Appointment.date.desc())
        .all()
    )
    seen: dict[str, dict] = {}
    for appointment in rows:
        patient = appointment.patient
        if patient is None or patient.id in seen:
            continue
        seen[patient.id] = {
            "id": patient.id,
            "name": patient.name,
            "phone": patient.phone,
            "gender": patient.gender,
            "blood_group": patient.blood_group,
            "is_pregnant": bool(patient.is_pregnant),
            "last_appointment": appointment.date,
            "last_status": appointment.status,
        }
    return list(seen.values())


@router.get("/patients/{patient_id}")
def get_patient_details(
    patient_id: str,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")

    if not sched.doctor_treats_patient(db, doctor.id, patient.id):
        # 404 rather than 403 on purpose: confirming that a record exists for a
        # given id is itself a disclosure when the caller has no relationship
        # to that patient.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")

    allergies = db.query(Allergy).filter(Allergy.patient_id == patient_id).all()
    conditions = db.query(Condition).filter(Condition.patient_id == patient_id).all()
    surgeries = db.query(Surgery).filter(Surgery.patient_id == patient_id).all()
    medications = db.query(Medication).filter(Medication.patient_id == patient_id).all()
    appointments = (
        db.query(Appointment)
        .filter(Appointment.patient_id == patient_id, Appointment.doctor_id == doctor.id)
        .order_by(Appointment.date.desc())
        .all()
    )

    return {
        "patient": PatientOut.model_validate(patient),
        "allergies": [AllergyOut.model_validate(a) for a in allergies],
        "conditions": [ConditionOut.model_validate(c) for c in conditions],
        "surgeries": [
            {"id": s.id, "name": s.name, "year": s.year, "hospital": s.hospital, "notes": s.notes}
            for s in surgeries
        ],
        "medications": [
            {
                "id": m.id,
                "raw_name": m.raw_name,
                "dosage": m.dosage,
                "frequency": m.frequency,
                "instructions": m.instructions,
            }
            for m in medications
        ],
        "appointments": [_serialise(a, with_patient=False) for a in appointments],
    }


# ------------------------------------------------- editing patient records ---
#
# A clinician correcting a record is normal: patients mistype their blood
# group, forget a surgery, or record an allergy as "mild" that put them in
# hospital. Every change here is written to PatientRecordEdit, because an edit
# with no trace of who made it is not a medical record.


def _audit(
    db: Session,
    patient_id: str,
    doctor_id: str,
    field: str,
    old_value,
    new_value,
    reason: str | None,
) -> None:
    db.add(
        PatientRecordEdit(
            patient_id=patient_id,
            doctor_id=doctor_id,
            field=field,
            old_value=None if old_value is None else str(old_value),
            new_value=None if new_value is None else str(new_value),
            reason=reason,
        )
    )


def _patient_for_doctor(db: Session, doctor: Doctor, patient_id: str) -> Patient:
    """
    Loads a patient only if this doctor has a legitimate claim to them.

    404 rather than 403 on purpose: confirming a record exists for a given id
    is itself a disclosure when the caller has no relationship to that patient.
    """
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient or not sched.doctor_treats_patient(db, doctor.id, patient.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return patient


@router.patch("/patients/{patient_id}", response_model=PatientOut)
def update_patient_record(
    patient_id: str,
    payload: DoctorPatientUpdate,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    patient = _patient_for_doctor(db, doctor, patient_id)
    data = payload.model_dump(exclude_unset=True)
    reason = data.pop("reason", None)

    changed = 0
    for field, new_value in data.items():
        old_value = getattr(patient, field, None)
        if old_value == new_value:
            continue
        setattr(patient, field, new_value)
        _audit(db, patient.id, doctor.id, field, old_value, new_value, reason)
        changed += 1

    if changed:
        db.commit()
        db.refresh(patient)
        # The chatbot answers from a file rendered off this record, so a
        # correction that never reaches the file would leave the assistant
        # quoting the old value back at the patient.
        write_patient_file(db, patient.id)
    return patient


@router.post(
    "/patients/{patient_id}/allergies",
    response_model=AllergyOut,
    status_code=status.HTTP_201_CREATED,
)
def add_patient_allergy(
    patient_id: str,
    payload: AllergyIn,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    patient = _patient_for_doctor(db, doctor, patient_id)
    row = Allergy(patient_id=patient.id, **payload.model_dump())
    db.add(row)
    _audit(
        db,
        patient.id,
        doctor.id,
        "allergy.added",
        None,
        f"{payload.allergen} ({payload.severity})",
        None,
    )
    db.commit()
    db.refresh(row)
    write_patient_file(db, patient.id)
    return row


@router.delete(
    "/patients/{patient_id}/allergies/{allergy_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_patient_allergy(
    patient_id: str,
    allergy_id: str,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    patient = _patient_for_doctor(db, doctor, patient_id)
    row = (
        db.query(Allergy).filter(Allergy.id == allergy_id, Allergy.patient_id == patient.id).first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Allergy not found")
    # Removing an allergy is the most dangerous edit in this file -- it switches
    # off a safety check -- so the audit entry keeps what was deleted.
    _audit(
        db,
        patient.id,
        doctor.id,
        "allergy.removed",
        f"{row.allergen} ({row.severity})",
        None,
        None,
    )
    db.delete(row)
    db.commit()
    write_patient_file(db, patient.id)


@router.post(
    "/patients/{patient_id}/conditions",
    response_model=ConditionOut,
    status_code=status.HTTP_201_CREATED,
)
def add_patient_condition(
    patient_id: str,
    payload: ConditionIn,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    patient = _patient_for_doctor(db, doctor, patient_id)
    row = Condition(patient_id=patient.id, **payload.model_dump())
    db.add(row)
    _audit(db, patient.id, doctor.id, "condition.added", None, payload.name, None)
    db.commit()
    db.refresh(row)
    write_patient_file(db, patient.id)
    return row


@router.delete(
    "/patients/{patient_id}/conditions/{condition_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_patient_condition(
    patient_id: str,
    condition_id: str,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    patient = _patient_for_doctor(db, doctor, patient_id)
    row = (
        db.query(Condition)
        .filter(Condition.id == condition_id, Condition.patient_id == patient.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Condition not found")
    _audit(db, patient.id, doctor.id, "condition.removed", row.name, None, None)
    db.delete(row)
    db.commit()
    write_patient_file(db, patient.id)


@router.post("/patients/{patient_id}/surgeries", status_code=status.HTTP_201_CREATED)
def add_patient_surgery(
    patient_id: str,
    payload: SurgeryIn,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    patient = _patient_for_doctor(db, doctor, patient_id)
    row = Surgery(patient_id=patient.id, **payload.model_dump())
    db.add(row)
    _audit(db, patient.id, doctor.id, "surgery.added", None, payload.name, None)
    db.commit()
    db.refresh(row)
    write_patient_file(db, patient.id)
    return {
        "id": row.id,
        "name": row.name,
        "year": row.year,
        "hospital": row.hospital,
        "notes": row.notes,
    }


@router.delete(
    "/patients/{patient_id}/surgeries/{surgery_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_patient_surgery(
    patient_id: str,
    surgery_id: str,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    patient = _patient_for_doctor(db, doctor, patient_id)
    row = (
        db.query(Surgery).filter(Surgery.id == surgery_id, Surgery.patient_id == patient.id).first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Surgery not found")
    _audit(db, patient.id, doctor.id, "surgery.removed", row.name, None, None)
    db.delete(row)
    db.commit()
    write_patient_file(db, patient.id)


@router.get("/patients/{patient_id}/edits", response_model=list[RecordEditOut])
def list_record_edits(
    patient_id: str,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """
    Who changed what, newest first. Includes edits by other doctors: the point
    of the trail is that no clinician's changes are invisible.
    """
    patient = _patient_for_doctor(db, doctor, patient_id)
    rows = (
        db.query(PatientRecordEdit)
        .options(joinedload(PatientRecordEdit.doctor))
        .filter(PatientRecordEdit.patient_id == patient.id)
        .order_by(PatientRecordEdit.created_at.desc())
        .limit(100)
        .all()
    )
    out = []
    for row in rows:
        item = RecordEditOut.model_validate(row)
        item.doctor_name = row.doctor.name if row.doctor else None
        out.append(item)
    return out


@router.get("/patients/{patient_id}/summary", response_model=PatientSummaryOut)
def get_patient_summary(
    patient_id: str,
    doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """
    The two minutes before a consultation, condensed.

    The structured half is computed, not written by a model -- allergies,
    pregnancy, safety flags, adherence and out-of-band vitals are facts a
    doctor must be able to trust exactly. The model only writes the narrative
    on top, and the response says which produced it.
    """
    patient = _patient_for_doctor(db, doctor, patient_id)
    summary = patient_summary_service.build(db, patient, doctor.id)
    return PatientSummaryOut(
        patient_id=summary.patient_id,
        patient_name=summary.patient_name,
        age_years=summary.age_years,
        narrative=summary.narrative,
        narrative_source=summary.narrative_source,
        highlights=[
            {"label": h.label, "detail": h.detail, "tone": h.tone} for h in summary.highlights
        ],
        medicines=summary.medicines,
        safety_flags=summary.safety_flags,
        vitals=summary.vitals,
        adherence=summary.adherence,
        last_seen=summary.last_seen,
        generated_at=summary.generated_at,
    )
