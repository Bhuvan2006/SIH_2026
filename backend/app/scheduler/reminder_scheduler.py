"""
Background reminder engine.

Runs once a minute, finds active Schedules whose time_of_day matches the
current clock time, and (a) ensures a pending AdherenceLog exists for
today so the patient has something to mark taken/skipped, and (b) fires
a notification through the configured NotifierProvider -- including a
drug-specific storage nudge pulled from DrugKnowledge when relevant
(e.g. insulin's refrigeration note), per build plan §6.5.

This is a simple polling design appropriate for a prototype. A
production system would use a durable job queue (e.g. Celery beat, or a
cloud scheduler + queue) rather than an in-process APScheduler instance,
so reminders survive restarts and scale across multiple app instances.
"""
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.db.database import SessionLocal
from app.models.models import AdherenceLog, AdherenceStatus, DrugKnowledge, Medication, Patient, Schedule
from app.services.notification_service import get_notifier

logger = logging.getLogger("arogya.scheduler")


def _due_today(time_of_day: str, now: datetime) -> bool:
    """
    True if this dose time has already arrived today.

    Deliberately "<= now" rather than "== this exact minute". Exact-minute
    matching silently loses a dose whenever the process isn't running at that
    precise moment -- a restart, a sleeping laptop, or a delayed tick -- and
    the patient never finds out. Comparing against the whole elapsed day means
    a late start still catches up on everything missed so far.
    """
    try:
        hh, mm = time_of_day.split(":")
        scheduled = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    except (ValueError, AttributeError):
        logger.warning("Skipping schedule with unparseable time_of_day=%r", time_of_day)
        return False
    return scheduled <= now


def _tick():
    now = datetime.now()
    db = SessionLocal()
    try:
        schedules = [
            s
            for s in db.query(Schedule).filter(Schedule.active == True).all()  # noqa: E712
            if _due_today(s.time_of_day, now)
        ]
        notifier = get_notifier()
        for schedule in schedules:
            already_logged = (
                db.query(AdherenceLog)
                .filter(
                    AdherenceLog.schedule_id == schedule.id,
                    AdherenceLog.scheduled_for >= now.replace(hour=0, minute=0, second=0, microsecond=0),
                )
                .first()
            )
            if already_logged:
                continue

            # Store when the dose was actually DUE, not when we noticed it, so
            # a catch-up after downtime still reads "due 08:00" rather than
            # the arbitrary time the server happened to come back up.
            hh, mm = schedule.time_of_day.split(":")
            scheduled_for = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)

            log = AdherenceLog(
                schedule_id=schedule.id, scheduled_for=scheduled_for, status=AdherenceStatus.PENDING
            )
            db.add(log)

            medication = db.query(Medication).filter(Medication.id == schedule.medication_id).first()
            if not medication:
                continue

            body = f"Time to take {medication.raw_name}"
            if medication.dosage:
                body += f" ({medication.dosage})"
            if medication.instructions:
                body += f". {medication.instructions}"

            if medication.matched_drug_id:
                drug = db.query(DrugKnowledge).filter(DrugKnowledge.id == medication.matched_drug_id).first()
                if drug and drug.storage_instructions:
                    body += f" Reminder — storage: {drug.storage_instructions}"

            patient = db.query(Patient).filter(Patient.id == medication.patient_id).first()

            notifier.send(
                patient_id=medication.patient_id,
                phone=patient.phone if patient else None,
                title="Medication reminder",
                body=body,
            )
        db.commit()
    except Exception:
        logger.exception("Reminder tick failed")
        db.rollback()
    finally:
        db.close()


_scheduler: BackgroundScheduler | None = None


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(_tick, "interval", minutes=1, id="reminder_tick", next_run_time=datetime.now())
    _scheduler.start()
    logger.info("Reminder scheduler started (checks every minute)")


def stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
