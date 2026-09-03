"""
Backfills realistic adherence history for ONE patient, so the dashboard has
something to show during development and demos.

    python scripts/seed_demo_adherence.py +919876500011 [--days 30] [--clear]

This writes fake AdherenceLog rows. It is a dev/demo tool only -- never run it
against real patient data, since adherence history is a clinical record.

The generated pattern is deliberately uneven rather than uniformly random:
morning doses are taken more reliably than evening ones, which is the pattern
real adherence data actually shows, and it makes the per-medicine and
worst-time-slot panels show something meaningful instead of noise.
"""
import argparse
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from app.db.database import SessionLocal  # noqa: E402
from app.models.models import (  # noqa: E402
    AdherenceLog,
    AdherenceStatus,
    Medication,
    Patient,
    Schedule,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("phone", help="patient phone, e.g. +919876500011")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--clear", action="store_true", help="delete this patient's existing logs first")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        patient = db.query(Patient).filter(Patient.phone == args.phone).first()
        if not patient:
            print(f"No patient with phone {args.phone}")
            return

        schedules = (
            db.query(Schedule)
            .join(Medication, Schedule.medication_id == Medication.id)
            .filter(
                Medication.patient_id == patient.id,
                Medication.is_confirmed == True,  # noqa: E712
                Schedule.active == True,  # noqa: E712
            )
            .all()
        )
        if not schedules:
            print("This patient has no active schedules — confirm a prescription first.")
            return

        if args.clear:
            ids = [s.id for s in schedules]
            deleted = (
                db.query(AdherenceLog).filter(AdherenceLog.schedule_id.in_(ids)).delete(
                    synchronize_session=False
                )
            )
            print(f"cleared {deleted} existing log(s)")

        random.seed(42)  # reproducible demo data
        today = datetime.now().date()
        created = 0

        for offset in range(args.days, 0, -1):
            day = today - timedelta(days=offset)
            for s in schedules:
                hh, mm = (int(x) for x in s.time_of_day.split(":"))
                scheduled_for = datetime.combine(day, datetime.min.time()).replace(hour=hh, minute=mm)

                # Evening doses are missed noticeably more often than morning
                # ones -- the pattern the time-of-day panel exists to surface.
                take_probability = 0.93 if hh < 12 else 0.68
                roll = random.random()
                if roll < take_probability:
                    status = AdherenceStatus.TAKEN
                elif roll < take_probability + 0.10:
                    status = AdherenceStatus.SNOOZED
                else:
                    status = AdherenceStatus.SKIPPED

                db.add(
                    AdherenceLog(
                        schedule_id=s.id,
                        scheduled_for=scheduled_for,
                        status=status,
                        recorded_at=scheduled_for + timedelta(minutes=random.randint(1, 90)),
                    )
                )
                created += 1

        db.commit()
        print(f"created {created} adherence log(s) across {args.days} days for {patient.name or args.phone}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
