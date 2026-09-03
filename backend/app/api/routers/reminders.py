from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_patient
from app.db.database import get_db
from app.models.models import (
    AdherenceLog,
    AdherenceStatus,
    DrugKnowledge,
    Medication,
    Patient,
    Schedule,
)
from app.schemas.schemas import AdherenceUpdate, ScheduleOut, UpcomingReminder
from app.services.insights_service import compute_insights
from app.services.notification_service import get_notifier

router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.get("/schedules", response_model=list[ScheduleOut])
def list_schedules(patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)):
    return (
        db.query(Schedule)
        .join(Medication, Schedule.medication_id == Medication.id)
        .filter(Medication.patient_id == patient.id)
        .all()
    )


@router.get("/upcoming", response_model=list[UpcomingReminder])
def upcoming_today(patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)):
    """
    Today's reminder schedule for the patient, each entry annotated with
    today's adherence status if a log already exists (created either by
    the background scheduler when its time arrived, or synthesized here
    for times still ahead today).
    """
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    schedules = (
        db.query(Schedule)
        .join(Medication, Schedule.medication_id == Medication.id)
        .filter(Medication.patient_id == patient.id, Schedule.active == True)  # noqa: E712
        .all()
    )

    results: list[UpcomingReminder] = []
    for schedule in schedules:
        medication = db.query(Medication).filter(Medication.id == schedule.medication_id).first()
        if not medication:
            continue
        storage_note = None
        if medication.matched_drug_id:
            drug = db.query(DrugKnowledge).filter(DrugKnowledge.id == medication.matched_drug_id).first()
            if drug:
                storage_note = drug.storage_instructions

        log = (
            db.query(AdherenceLog)
            .filter(AdherenceLog.schedule_id == schedule.id, AdherenceLog.scheduled_for >= today_start)
            .order_by(AdherenceLog.scheduled_for.desc())
            .first()
        )

        results.append(
            UpcomingReminder(
                schedule_id=schedule.id,
                medication_id=medication.id,
                drug_name=medication.raw_name,
                time_of_day=schedule.time_of_day,
                dosage=medication.dosage,
                instructions=medication.instructions,
                storage_note=storage_note,
                adherence_log_id=log.id if log else None,
                status=log.status.value if log else "pending",
            )
        )

    results.sort(key=lambda r: r.time_of_day)
    return results


@router.post("/adherence/{schedule_id}")
def record_adherence(
    schedule_id: str,
    payload: AdherenceUpdate,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    schedule = (
        db.query(Schedule)
        .join(Medication, Schedule.medication_id == Medication.id)
        .filter(Schedule.id == schedule_id, Medication.patient_id == patient.id)
        .first()
    )
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")

    if payload.status not in (s.value for s in AdherenceStatus):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    log = (
        db.query(AdherenceLog)
        .filter(AdherenceLog.schedule_id == schedule.id, AdherenceLog.scheduled_for >= today_start)
        .order_by(AdherenceLog.scheduled_for.desc())
        .first()
    )
    if not log:
        log = AdherenceLog(schedule_id=schedule.id, scheduled_for=datetime.now())
        db.add(log)

    log.status = AdherenceStatus(payload.status)
    log.recorded_at = datetime.utcnow()
    db.commit()
    return {"schedule_id": schedule_id, "status": log.status.value, "recorded_at": log.recorded_at}


@router.get("/insights")
def dashboard_insights(
    window_days: int = 30,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    """
    Dashboard insights derived from data already in the database: dose
    adherence, per-medicine breakdown, streaks, refill runway, and generic
    price savings. See insights_service for how adherence is computed and why
    it is not presented as a clinical PDC figure.
    """
    i = compute_insights(db, patient.id, window_days=max(7, min(window_days, 180)))
    return {
        "has_enough_data": i.has_enough_data,
        "days_tracked": i.days_tracked,
        "adherence": {
            "percent": i.adherence_percent,
            "target_percent": i.target_percent,
            "doses_taken": i.doses_taken,
            "doses_expected": i.doses_expected,
            "days_covered": i.days_covered,
            "days_total": i.days_total,
            "daily_series": i.daily_series,
        },
        "per_medicine": [asdict(m) for m in i.per_medicine],
        "worst_slot": i.worst_slot,
        "streak": {"current": i.current_streak, "best": i.best_streak},
        "refills": [asdict(r) for r in i.refills],
        "savings": {
            "total_per_pack": i.total_saving_per_pack,
            "items": [asdict(s) for s in i.savings],
        },
    }


@router.get("/due")
def due_now(patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)):
    """
    Doses that are due right now and still unacknowledged (status "pending").

    This is what makes reminders actually visible: the mock/SMS notifier only
    writes to a log or an external channel, so without an in-app surface a
    patient sitting on the dashboard would never see that a dose came due.
    The frontend polls this and shows a banner.
    """
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    rows = (
        db.query(AdherenceLog, Schedule, Medication)
        .join(Schedule, AdherenceLog.schedule_id == Schedule.id)
        .join(Medication, Schedule.medication_id == Medication.id)
        .filter(
            Medication.patient_id == patient.id,
            AdherenceLog.scheduled_for >= today_start,
            AdherenceLog.status == AdherenceStatus.PENDING,
            Schedule.active == True,  # noqa: E712
        )
        .order_by(AdherenceLog.scheduled_for.asc())
        .all()
    )

    now = datetime.now()
    out = []
    for log, schedule, medication in rows:
        minutes_late = int((now - log.scheduled_for).total_seconds() // 60)
        out.append(
            {
                "schedule_id": schedule.id,
                "adherence_log_id": log.id,
                "drug_name": medication.raw_name,
                "dosage": medication.dosage,
                "instructions": medication.instructions,
                "time_of_day": schedule.time_of_day,
                "scheduled_for": log.scheduled_for,
                "minutes_late": max(0, minutes_late),
            }
        )
    return out


@router.post("/test-notification")
def send_test_notification(patient: Patient = Depends(get_current_patient)):
    """
    Sends a one-off test reminder text to the patient's registered phone
    number via the configured NOTIFICATION_PROVIDER. Useful for confirming
    MSG91 (or another real provider) is wired up correctly before relying
    on the automatic per-minute reminder scheduler.
    """
    notifier = get_notifier()
    note = notifier.send(
        patient_id=patient.id,
        phone=patient.phone,
        title="Arogya test reminder",
        body="This is a test message from Arogya to confirm reminders reach your phone.",
    )
    return {"channel": note.channel, "sent_at": note.sent_at, "phone": patient.phone}


@router.patch("/schedules/{schedule_id}/pause")
def pause_schedule(
    schedule_id: str,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    schedule = (
        db.query(Schedule)
        .join(Medication, Schedule.medication_id == Medication.id)
        .filter(Schedule.id == schedule_id, Medication.patient_id == patient.id)
        .first()
    )
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    schedule.active = not schedule.active
    db.commit()
    return {"schedule_id": schedule_id, "active": schedule.active}
