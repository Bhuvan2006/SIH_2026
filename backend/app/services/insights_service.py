"""
Dashboard insights computed from data the app already collects.

Everything here reads existing tables -- AdherenceLog, Schedule, Medication,
PriceEntry -- so there is no new vendor, permission, or device integration
involved.

A note on PDC
-------------
The clinical standard for chronic-medication adherence is Proportion of Days
Covered (PDC), endorsed by the Pharmacy Quality Alliance, where 80% is the
threshold above which a medicine is likely to deliver its benefit. Real PDC is
computed from pharmacy REFILL records: days on which the patient had supply in
hand.

Arogya has no refill data. What it has is per-dose logs, so we compute the
closest honest analogue: a day counts as "covered" when every dose scheduled
for that day was marked taken. That is stricter than refill-based PDC (which
assumes a dispensed medicine was consumed), and it is labelled in the UI as
"doses taken" rather than presented as a clinical PDC figure. The 80% reference
line is kept because it is the number a clinician will recognise.
"""
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.models import (
    AdherenceLog,
    AdherenceStatus,
    DrugKnowledge,
    Medication,
    PriceEntry,
    Schedule,
)

logger = logging.getLogger("arogya.insights")

# Below this many days of logged history, every percentage is noise. The UI
# shows an honest "not enough history yet" state instead of a fake 100%.
MIN_DAYS_FOR_STATS = 3
PDC_TARGET = 80.0


@dataclass
class MedicineAdherence:
    medication_id: str
    name: str
    taken: int
    missed: int
    total: int
    percent: float


@dataclass
class RefillRunway:
    medication_id: str
    name: str
    days_left: int
    runs_out_on: str
    duration_days: int


@dataclass
class SavingOpportunity:
    medication_id: str
    name: str
    current_product: str
    current_price: float
    cheapest_product: str
    cheapest_price: float
    saving_per_pack: float
    unit: str


@dataclass
class DashboardInsights:
    has_enough_data: bool
    days_tracked: int

    adherence_percent: float
    doses_taken: int
    doses_expected: int
    days_covered: int
    days_total: int
    target_percent: float = PDC_TARGET

    daily_series: list[dict] = field(default_factory=list)  # [{date, expected, taken}]
    per_medicine: list[MedicineAdherence] = field(default_factory=list)
    worst_slot: dict | None = None

    current_streak: int = 0
    best_streak: int = 0

    refills: list[RefillRunway] = field(default_factory=list)
    savings: list[SavingOpportunity] = field(default_factory=list)
    total_saving_per_pack: float = 0.0


def _active_schedules(db: Session, patient_id: str) -> list[Schedule]:
    return (
        db.query(Schedule)
        .join(Medication, Schedule.medication_id == Medication.id)
        .filter(
            Medication.patient_id == patient_id,
            Medication.is_confirmed == True,  # noqa: E712
            Schedule.active == True,  # noqa: E712
        )
        .all()
    )


def compute_insights(db: Session, patient_id: str, window_days: int = 30) -> DashboardInsights:
    today = date.today()
    window_start = datetime.combine(today - timedelta(days=window_days - 1), datetime.min.time())

    schedules = _active_schedules(db, patient_id)
    schedule_ids = [s.id for s in schedules]

    logs = (
        db.query(AdherenceLog)
        .filter(
            AdherenceLog.schedule_id.in_(schedule_ids) if schedule_ids else False,
            AdherenceLog.scheduled_for >= window_start,
        )
        .all()
        if schedule_ids
        else []
    )

    # Distinct days that actually have logged history. Percentages computed off
    # fewer than MIN_DAYS_FOR_STATS days mislead more than they inform.
    logged_days = {log.scheduled_for.date() for log in logs}
    days_tracked = len(logged_days)

    insights = DashboardInsights(
        has_enough_data=days_tracked >= MIN_DAYS_FOR_STATS,
        days_tracked=days_tracked,
        adherence_percent=0.0,
        doses_taken=0,
        doses_expected=0,
        days_covered=0,
        days_total=days_tracked,
    )

    # ---- Dose-level adherence + daily series -----------------------------
    by_day: dict[date, dict[str, int]] = {}
    for log in logs:
        day = log.scheduled_for.date()
        bucket = by_day.setdefault(day, {"expected": 0, "taken": 0})
        bucket["expected"] += 1
        if log.status == AdherenceStatus.TAKEN:
            bucket["taken"] += 1

    insights.doses_expected = sum(b["expected"] for b in by_day.values())
    insights.doses_taken = sum(b["taken"] for b in by_day.values())
    insights.days_covered = sum(
        1 for b in by_day.values() if b["expected"] > 0 and b["taken"] == b["expected"]
    )
    if insights.doses_expected:
        insights.adherence_percent = round(
            insights.doses_taken / insights.doses_expected * 100, 1
        )

    insights.daily_series = [
        {"date": d.isoformat(), "expected": by_day[d]["expected"], "taken": by_day[d]["taken"]}
        for d in sorted(by_day)
    ]

    # ---- Per-medicine, worst first ---------------------------------------
    sched_to_med = {s.id: s.medication_id for s in schedules}
    med_rows = {
        m.id: m
        for m in db.query(Medication).filter(
            Medication.patient_id == patient_id, Medication.is_confirmed == True  # noqa: E712
        )
    }
    per_med: dict[str, dict[str, int]] = {}
    for log in logs:
        med_id = sched_to_med.get(log.schedule_id)
        if not med_id:
            continue
        b = per_med.setdefault(med_id, {"taken": 0, "total": 0})
        b["total"] += 1
        if log.status == AdherenceStatus.TAKEN:
            b["taken"] += 1

    for med_id, b in per_med.items():
        med = med_rows.get(med_id)
        if not med:
            continue
        name = med.matched_drug.generic_name if med.matched_drug else med.raw_name
        pct = round(b["taken"] / b["total"] * 100, 1) if b["total"] else 0.0
        insights.per_medicine.append(
            MedicineAdherence(
                medication_id=med_id,
                name=name,
                taken=b["taken"],
                missed=b["total"] - b["taken"],
                total=b["total"],
                percent=pct,
            )
        )
    # Worst first: the medicine needing attention should be the one you see.
    insights.per_medicine.sort(key=lambda m: m.percent)

    # ---- Which time slot gets missed most ---------------------------------
    slot: dict[str, dict[str, int]] = {}
    sched_time = {s.id: s.time_of_day for s in schedules}
    for log in logs:
        t = sched_time.get(log.schedule_id)
        if not t:
            continue
        b = slot.setdefault(t, {"taken": 0, "total": 0})
        b["total"] += 1
        if log.status == AdherenceStatus.TAKEN:
            b["taken"] += 1
    missed_slots = [
        {"time_of_day": t, "missed": b["total"] - b["taken"], "total": b["total"]}
        for t, b in slot.items()
        if b["total"] - b["taken"] > 0
    ]
    if missed_slots:
        insights.worst_slot = max(missed_slots, key=lambda s: s["missed"])

    # ---- Streaks (forgiving: today counts only once fully taken) ----------
    # Walking backwards from yesterday means a day still in progress never
    # breaks a streak the patient is on track to keep.
    def day_covered(d: date) -> bool:
        b = by_day.get(d)
        return bool(b and b["expected"] > 0 and b["taken"] == b["expected"])

    current = 0
    if day_covered(today):
        current = 1
    cursor = today - timedelta(days=1)
    while day_covered(cursor):
        current += 1
        cursor -= timedelta(days=1)
    insights.current_streak = current

    best = run = 0
    for d in sorted(by_day):
        if day_covered(d):
            run += 1
            best = max(best, run)
        else:
            run = 0
    insights.best_streak = max(best, current)

    # ---- Refill runway ----------------------------------------------------
    for med in med_rows.values():
        if not med.duration_days or not med.created_at:
            continue
        runs_out = med.created_at.date() + timedelta(days=med.duration_days)
        days_left = (runs_out - today).days
        if days_left < -7:
            continue  # long finished; not useful to show
        name = med.matched_drug.generic_name if med.matched_drug else med.raw_name
        insights.refills.append(
            RefillRunway(
                medication_id=med.id,
                name=name,
                days_left=days_left,
                runs_out_on=runs_out.isoformat(),
                duration_days=med.duration_days,
            )
        )
    insights.refills.sort(key=lambda r: r.days_left)

    # ---- Generic savings --------------------------------------------------
    # Compares the priciest listed product against the cheapest equivalent for
    # each medicine the patient is actually on. Reported per pack, NOT
    # annualised: we don't know pack size or doses-per-pack, so a yearly figure
    # would be invented.
    for med in med_rows.values():
        if not med.matched_drug_id:
            continue
        entries = (
            db.query(PriceEntry).filter(PriceEntry.drug_id == med.matched_drug_id).all()
        )
        if len(entries) < 2:
            continue
        cheapest = min(entries, key=lambda e: e.price_inr)
        costliest = max(entries, key=lambda e: e.price_inr)
        gap = round(costliest.price_inr - cheapest.price_inr, 2)
        if gap <= 0:
            continue
        drug = db.query(DrugKnowledge).filter(DrugKnowledge.id == med.matched_drug_id).first()
        insights.savings.append(
            SavingOpportunity(
                medication_id=med.id,
                name=drug.generic_name if drug else med.raw_name,
                current_product=costliest.product_name,
                current_price=costliest.price_inr,
                cheapest_product=cheapest.product_name,
                cheapest_price=cheapest.price_inr,
                saving_per_pack=gap,
                unit=cheapest.unit,
            )
        )
    insights.savings.sort(key=lambda s: s.saving_per_pack, reverse=True)
    insights.total_saving_per_pack = round(sum(s.saving_per_pack for s in insights.savings), 2)

    return insights
