"""
Creates demo doctors with real clinic hours.

    python scripts/seed_doctors.py            # create / refresh
    python scripts/seed_doctors.py --clear    # remove them again

Each doctor gets DIFFERENT hours on purpose. With one shared hardcoded
timetable the booking screen looked plausible but proved nothing; three
doctors who sit on different days is what shows the schedule is actually
per-doctor -- and lets a demo land on "Dr Rao does not hold clinic on
Wednesdays" instead of an unexplained empty list.

THIS IS FABRICATED DEMO DATA. Clear it before the database is used for
anything real.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import SessionLocal  # noqa: E402
from app.models.models import (  # noqa: E402
    Appointment,
    Doctor,
    DoctorAvailability,
    DoctorTimeOff,
)

DOCTORS = [
    {
        "phone": "+919000000001",
        "name": "Dr. Meera Iyer",
        "specialization": "Obstetrics & Gynaecology",
        "license_no": "KMC-48221",
        "clinic_name": "Sunrise Women's Clinic",
        "clinic_address": "22 MG Road, Bengaluru 560001",
        "consultation_fee_inr": 600.0,
        "languages": "English, Hindi, Kannada",
        # Full week except Sunday, morning and evening OPD.
        "hours": [(d, "09:00", "13:00", 20) for d in range(0, 6)]
        + [(d, "17:00", "20:00", 20) for d in range(0, 5)],
    },
    {
        "phone": "+919000000002",
        "name": "Dr. Anand Rao",
        "specialization": "General Physician",
        "license_no": "KMC-31907",
        "clinic_name": "Jayanagar Family Clinic",
        "clinic_address": "8th Main, Jayanagar 4th Block, Bengaluru 560011",
        "consultation_fee_inr": 350.0,
        "languages": "English, Kannada, Tamil",
        # Deliberately NOT Wednesday, so the "doesn't hold clinic" path is
        # reachable in a demo without waiting for a Sunday.
        "hours": [(d, "10:00", "14:00", 15) for d in (0, 1, 3, 4, 5)],
    },
    {
        "phone": "+919000000003",
        "name": "Dr. Fatima Sheikh",
        "specialization": "Endocrinology (Diabetes & Thyroid)",
        "license_no": "KMC-52664",
        "clinic_name": "Metabolic Care Centre",
        "clinic_address": "Indiranagar 100ft Road, Bengaluru 560038",
        "consultation_fee_inr": 800.0,
        "languages": "English, Hindi, Urdu",
        # Evenings only, twice a week, longer appointments.
        "hours": [(d, "16:00", "19:00", 30) for d in (1, 4)],
    },
]


def clear(db) -> int:
    removed = 0
    for spec in DOCTORS:
        doctor = db.query(Doctor).filter(Doctor.phone == spec["phone"]).first()
        if not doctor:
            continue
        # Appointments cascade from Doctor, but be explicit: leaving them would
        # orphan rows now that SQLite actually enforces the foreign key.
        db.query(Appointment).filter(Appointment.doctor_id == doctor.id).delete(
            synchronize_session=False
        )
        db.delete(doctor)
        removed += 1
    db.commit()
    return removed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clear", action="store_true", help="Remove the demo doctors and exit.")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if args.clear:
            print(f"removed {clear(db)} demo doctor(s)")
            return

        for spec in DOCTORS:
            hours = spec.pop("hours")
            doctor = db.query(Doctor).filter(Doctor.phone == spec["phone"]).first()
            if doctor is None:
                doctor = Doctor(**spec)
                db.add(doctor)
                db.flush()
            else:
                for field, value in spec.items():
                    setattr(doctor, field, value)
            doctor.profile_completed = bool(doctor.name and doctor.specialization)

            # Replace hours rather than appending, so re-running does not
            # stack duplicate sessions on the same weekday.
            db.query(DoctorAvailability).filter(
                DoctorAvailability.doctor_id == doctor.id
            ).delete(synchronize_session=False)
            db.query(DoctorTimeOff).filter(
                DoctorTimeOff.doctor_id == doctor.id
            ).delete(synchronize_session=False)

            for weekday, start, end, minutes in hours:
                db.add(
                    DoctorAvailability(
                        doctor_id=doctor.id,
                        weekday=weekday,
                        start_time=start,
                        end_time=end,
                        slot_minutes=minutes,
                    )
                )
            spec["hours"] = hours  # restore for a clean second run in-process

        db.commit()

        print(f"{len(DOCTORS)} doctors ready. Log in at /doctor/login with OTP 000000:\n")
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for spec in DOCTORS:
            doctor = db.query(Doctor).filter(Doctor.phone == spec["phone"]).first()
            sessions = (
                db.query(DoctorAvailability)
                .filter(DoctorAvailability.doctor_id == doctor.id)
                .order_by(DoctorAvailability.weekday, DoctorAvailability.start_time)
                .all()
            )
            open_days = sorted({days[s.weekday] for s in sessions})
            print(f"  {doctor.phone}  {doctor.name}")
            print(f"      {doctor.specialization} · Rs{doctor.consultation_fee_inr:.0f}")
            print(f"      {len(sessions)} sessions across {', '.join(open_days)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
