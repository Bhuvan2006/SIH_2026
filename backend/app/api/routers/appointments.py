"""
Patient-facing appointment booking.

Every rule about whether a slot exists or may be taken lives in
appointment_service, shared with the doctor-side router, so the two cannot
disagree about what is bookable.
"""
from datetime import date as date_cls
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.security import get_current_patient
from app.db.database import get_db
from app.models.models import Appointment, Doctor, Patient
from app.schemas.schemas import (
    AppointmentIn,
    AppointmentOut,
    DaySlotsOut,
    DoctorOut,
)
from app.services import appointment_service as sched

router = APIRouter(prefix="/appointments", tags=["appointments"])


def _serialise(appointment: Appointment, *, with_doctor=True, with_patient=False) -> AppointmentOut:
    out = AppointmentOut.model_validate(appointment)
    out.time_slot_label = sched.format_slot(appointment.time_slot)
    try:
        appointment_at = datetime.combine(
            sched.parse_date(appointment.date), sched.parse_time(appointment.time_slot)
        )
        out.is_past = appointment_at < datetime.now()
    except sched.SchedulingError:
        out.is_past = False
    if not with_doctor:
        out.doctor = None
    if not with_patient:
        out.patient = None
    return out


@router.get("/doctors", response_model=list[DoctorOut])
def list_doctors(db: Session = Depends(get_db), patient: Patient = Depends(get_current_patient)):
    """
    Doctors a patient can actually book.

    Ones who have not filled in a name are hidden: they appeared in the picker
    as a blank row, and a patient cannot sensibly choose "null".
    """
    return (
        db.query(Doctor)
        .filter(Doctor.name.isnot(None), Doctor.name != "")
        .order_by(Doctor.name.asc())
        .all()
    )


@router.get("/doctors/{doctor_id}/slots", response_model=DaySlotsOut)
def get_available_slots(
    doctor_id: str,
    date: str,
    db: Session = Depends(get_db),
    patient: Patient = Depends(get_current_patient),
):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Doctor not found")
    try:
        on = sched.parse_date(date)
    except sched.SchedulingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return sched.day_view(db, doctor, on)


@router.post("/book", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
def book_appointment(
    payload: AppointmentIn,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    doctor = db.query(Doctor).filter(Doctor.id == payload.doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Doctor not found")

    try:
        sched.validate_booking(db, doctor, payload.date, payload.time_slot)
    except sched.SchedulingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # One live appointment per patient per doctor per day. Two slots with the
    # same doctor on the same morning is nearly always a mis-tap.
    same_day = (
        db.query(Appointment)
        .filter(
            Appointment.patient_id == patient.id,
            Appointment.doctor_id == doctor.id,
            Appointment.date == payload.date,
            Appointment.status.in_(sched.ACTIVE_STATUSES),
        )
        .first()
    )
    if same_day:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"You already have a {sched.format_slot(same_day.time_slot)} appointment with "
                f"{doctor.name or 'this doctor'} that day."
            ),
        )

    appointment = Appointment(
        patient_id=patient.id,
        doctor_id=doctor.id,
        date=payload.date,
        time_slot=payload.time_slot,
        notes=payload.notes,
        status="pending",
        created_by="patient",
    )
    db.add(appointment)
    try:
        db.commit()
    except IntegrityError:
        # The unique index caught a slot taken between our check and this
        # insert -- the race the check alone cannot close.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That slot was taken a moment ago. Please pick another.",
        ) from None
    db.refresh(appointment)
    return _serialise(appointment)


@router.get("/my", response_model=list[AppointmentOut])
def get_my_appointments(
    patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)
):
    appointments = (
        db.query(Appointment)
        .options(joinedload(Appointment.doctor))
        .filter(Appointment.patient_id == patient.id)
        .order_by(Appointment.date.desc(), Appointment.time_slot.desc())
        .all()
    )
    return [_serialise(a) for a in appointments]


@router.patch("/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel_appointment(
    appointment_id: str,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    appointment = (
        db.query(Appointment)
        .options(joinedload(Appointment.doctor))
        .filter(Appointment.id == appointment_id, Appointment.patient_id == patient.id)
        .first()
    )
    if not appointment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

    if appointment.status == "cancelled":
        return _serialise(appointment)
    if appointment.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This appointment has already taken place.",
        )

    appointment.status = "cancelled"
    appointment.cancelled_by = "patient"
    db.commit()
    db.refresh(appointment)
    return _serialise(appointment)
