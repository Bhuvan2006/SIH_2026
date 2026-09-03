"""
Appointment scheduling: whose slots exist, when, and who may book them.

The prototype started with a hardcoded list of twelve times, identical for
every doctor and every date. That meant a patient could book Sunday 4:30pm
with a doctor who only sits Monday mornings, the doctor had no way to say
otherwise, and every doctor in the system appeared to keep the same hours.

Slots are now generated from the doctor's own recurring availability, minus
the dates they have blocked off, minus what is already booked. Everything that
decides whether a booking is legal lives here so the patient-side and
doctor-side routers cannot drift apart on the rules.

Times are stored 24-hour ("14:30") rather than "02:30 PM": they sort
correctly as strings, compare without parsing, and leave formatting to the
UI, which is the only place that knows the reader's locale.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime, time, timedelta

from sqlalchemy.orm import Session

from app.models.models import (
    Appointment,
    Doctor,
    DoctorAvailability,
    DoctorTimeOff,
)

# Statuses that hold a slot. A cancelled appointment frees it again.
ACTIVE_STATUSES = ("pending", "confirmed")
TERMINAL_STATUSES = ("cancelled", "completed")
ALL_STATUSES = ACTIVE_STATUSES + TERMINAL_STATUSES

# How far ahead a patient may book. Long enough to be useful, short enough
# that a doctor changing their hours doesn't invalidate months of diary.
MAX_BOOKING_HORIZON_DAYS = 60

# Default clinic hours given to a doctor who hasn't set any yet, so a new
# doctor is bookable immediately instead of appearing to have no practice.
# Monday-Saturday, morning and evening OPD -- the common Indian pattern.
DEFAULT_AVAILABILITY = [
    {"weekday": d, "start_time": "09:00", "end_time": "13:00", "slot_minutes": 30}
    for d in range(0, 6)
] + [
    {"weekday": d, "start_time": "17:00", "end_time": "20:00", "slot_minutes": 30}
    for d in range(0, 6)
]

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class SchedulingError(ValueError):
    """A booking that cannot be honoured. Carries a message meant for the patient."""


@dataclass
class SlotView:
    time_slot: str
    available: bool
    reason: str | None = None


def parse_date(value: str) -> date_cls:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise SchedulingError("Date must look like 2026-09-10.") from exc


def parse_time(value: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError) as exc:
        raise SchedulingError("Time must look like 14:30.") from exc


def format_slot(value: str) -> str:
    """24-hour to a human label, for notifications and printed summaries."""
    try:
        return datetime.strptime(value, "%H:%M").strftime("%I:%M %p").lstrip("0")
    except (TypeError, ValueError):
        return value


def ensure_default_availability(db: Session, doctor: Doctor) -> None:
    """Give a doctor standard clinic hours the first time anyone asks for
    their slots, so a freshly registered doctor is immediately bookable."""
    existing = (
        db.query(DoctorAvailability).filter(DoctorAvailability.doctor_id == doctor.id).count()
    )
    if existing:
        return
    for row in DEFAULT_AVAILABILITY:
        db.add(DoctorAvailability(doctor_id=doctor.id, **row))
    db.commit()


def generate_slots_for_day(db: Session, doctor_id: str, on: date_cls) -> list[str]:
    """Every slot the doctor's schedule creates that day, booked or not."""
    rows = (
        db.query(DoctorAvailability)
        .filter(
            DoctorAvailability.doctor_id == doctor_id,
            DoctorAvailability.weekday == on.weekday(),
            DoctorAvailability.active.is_(True),
        )
        .all()
    )

    slots: list[str] = []
    for row in rows:
        start = parse_time(row.start_time)
        end = parse_time(row.end_time)
        step = max(5, int(row.slot_minutes or 30))
        cursor = datetime.combine(on, start)
        finish = datetime.combine(on, end)
        # A session that ends before it starts would loop forever; treat it as
        # a data error and skip rather than hang the request.
        if finish <= cursor:
            continue
        while cursor + timedelta(minutes=step) <= finish:
            slots.append(cursor.strftime("%H:%M"))
            cursor += timedelta(minutes=step)

    # Sessions can overlap if a doctor enters odd hours; de-duplicate.
    return sorted(set(slots))


def is_day_off(db: Session, doctor_id: str, on: date_cls) -> str | None:
    row = (
        db.query(DoctorTimeOff)
        .filter(DoctorTimeOff.doctor_id == doctor_id, DoctorTimeOff.date == on.isoformat())
        .first()
    )
    if not row:
        return None
    return row.reason or "The doctor is not available on this date."


def booked_slots(db: Session, doctor_id: str, on: date_cls) -> set[str]:
    rows = (
        db.query(Appointment.time_slot)
        .filter(
            Appointment.doctor_id == doctor_id,
            Appointment.date == on.isoformat(),
            Appointment.status.in_(ACTIVE_STATUSES),
        )
        .all()
    )
    return {r[0] for r in rows}


def day_view(db: Session, doctor: Doctor, on: date_cls) -> dict:
    """
    The full picture for one date: which slots exist, which are taken, and if
    nothing is bookable, WHY. "No slots available" with no explanation is the
    kind of dead end that makes a patient give up; "Dr Iyer does not hold
    clinic on Sundays" tells them what to do instead.
    """
    ensure_default_availability(db, doctor)

    today = date_cls.today()
    if on < today:
        return {"date": on.isoformat(), "slots": [], "closed_reason": "That date has already passed."}
    if (on - today).days > MAX_BOOKING_HORIZON_DAYS:
        return {
            "date": on.isoformat(),
            "slots": [],
            "closed_reason": f"Booking opens {MAX_BOOKING_HORIZON_DAYS} days ahead.",
        }

    off_reason = is_day_off(db, doctor.id, on)
    if off_reason:
        return {"date": on.isoformat(), "slots": [], "closed_reason": off_reason}

    generated = generate_slots_for_day(db, doctor.id, on)
    if not generated:
        return {
            "date": on.isoformat(),
            "slots": [],
            "closed_reason": (
                f"{doctor.name or 'This doctor'} does not hold clinic on "
                f"{WEEKDAY_NAMES[on.weekday()]}s."
            ),
        }

    taken = booked_slots(db, doctor.id, on)
    now = datetime.now()
    views: list[SlotView] = []
    for slot in generated:
        if slot in taken:
            views.append(SlotView(slot, False, "Already booked"))
        elif on == today and datetime.combine(on, parse_time(slot)) <= now:
            # A slot earlier today is not bookable, but showing it greyed out
            # reads more honestly than a morning that silently vanishes.
            views.append(SlotView(slot, False, "Time has passed"))
        else:
            views.append(SlotView(slot, True))

    return {"date": on.isoformat(), "slots": views, "closed_reason": None}


def validate_booking(
    db: Session,
    doctor: Doctor,
    date_str: str,
    time_slot: str,
    *,
    allow_same_day_past: bool = False,
) -> None:
    """
    Raises SchedulingError unless this slot can actually be booked.

    None of these checks existed: the API accepted a booking on 2020-01-01, a
    time_slot of "3am in the morning", and a doctor_id that matched no doctor.
    """
    on = parse_date(date_str)
    today = date_cls.today()

    if on < today:
        raise SchedulingError("That date has already passed.")
    if (on - today).days > MAX_BOOKING_HORIZON_DAYS:
        raise SchedulingError(f"Appointments can only be booked {MAX_BOOKING_HORIZON_DAYS} days ahead.")

    off_reason = is_day_off(db, doctor.id, on)
    if off_reason:
        raise SchedulingError(off_reason)

    generated = generate_slots_for_day(db, doctor.id, on)
    if time_slot not in generated:
        raise SchedulingError(
            f"{format_slot(time_slot)} is not one of "
            f"{doctor.name or 'this doctor'}'s slots on {on.strftime('%d %b %Y')}."
        )

    if not allow_same_day_past and on == today:
        if datetime.combine(on, parse_time(time_slot)) <= datetime.now():
            raise SchedulingError("That time has already passed today.")

    if time_slot in booked_slots(db, doctor.id, on):
        raise SchedulingError("That slot has just been taken. Please pick another.")


def doctor_treats_patient(db: Session, doctor_id: str, patient_id: str) -> bool:
    """
    Whether a doctor has any legitimate claim to a patient's record.

    The doctor-facing patient endpoint had NO check at all: anyone who
    registered as a doctor with any phone number could read every patient's
    name, phone, allergies, conditions and medicines. An appointment between
    the two is the relationship that makes access defensible -- including a
    cancelled or completed one, since a doctor still needs the notes for
    someone they saw last month.
    """
    return (
        db.query(Appointment.id)
        .filter(Appointment.doctor_id == doctor_id, Appointment.patient_id == patient_id)
        .first()
        is not None
    )
