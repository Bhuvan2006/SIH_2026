"""
Creates a demo profile for a pregnant patient.

    python scripts/seed_pregnant_demo.py            # create / refresh
    python scripts/seed_pregnant_demo.py --clear    # remove it again

Persona: Priya Sharma, 28, 26 weeks pregnant, with gestational diabetes and
hypothyroidism -- the two conditions most commonly managed alongside an Indian
pregnancy, so the dashboard shows real antenatal monitoring rather than filler.

Her CURRENT medicines are all appropriate in pregnancy (folic acid, iron,
calcium, levothyroxine, metformin for GDM). That is deliberate: the demo should
open on a normal, safe record, so the safety system has somewhere to fall from.
The flags come from the prescription you upload live -- see
`scripts/make_demo_prescription.py`, which writes an image containing medicines
that are contraindicated in pregnancy.

THIS IS FABRICATED DEMO DATA. It must be removed (`--clear`) before the
database is used for anything real, and it is never written unless this script
is run explicitly.
"""
import argparse
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import SessionLocal  # noqa: E402
from app.models.models import (  # noqa: E402
    AdherenceLog,
    AdherenceStatus,
    Allergy,
    ConfirmationStatus,
    Condition,
    EmergencyContact,
    HealthMetric,
    Medication,
    Patient,
    Prescription,
    Schedule,
    Surgery,
)
from app.services.patient_file_service import write_patient_file  # noqa: E402

PHONE = "+919876500022"
NAME = "Priya Sharma"

# 26 weeks gone of 40, so the due date is 14 weeks out. Computed from today so
# the profile never drifts into "overdue" if the demo is given weeks later.
WEEKS_PREGNANT = 26
DUE_DATE = date.today() + timedelta(weeks=40 - WEEKS_PREGNANT)

# Standard Indian antenatal regimen. Every one of these is appropriate in
# pregnancy -- iron and folic acid are the government's own IFA programme,
# calcium is WHO-recommended for pre-eclampsia risk, levothyroxine treats the
# hypothyroidism, metformin manages the gestational diabetes.
MEDICINES = [
    {
        "raw_name": "Folvite 5mg Tablet",
        "generic": "Folic Acid",
        "dosage": "5mg",
        "frequency": "once daily",
        "instructions": "After breakfast",
        "times": ["09:00"],
    },
    {
        "raw_name": "Fefol Capsule",
        "generic": "Ferrous Sulphate + Folic Acid",
        "dosage": "150mg/0.5mg",
        "frequency": "once daily",
        "instructions": "After food — avoid tea or milk within an hour",
        "times": ["14:00"],
    },
    {
        "raw_name": "Shelcal 500 Tablet",
        "generic": "Calcium Carbonate + Vitamin D3",
        "dosage": "500mg",
        "frequency": "twice daily",
        "instructions": "After meals",
        "times": ["11:00", "21:00"],
    },
    {
        "raw_name": "Thyronorm 50mcg Tablet",
        "generic": "Levothyroxine",
        "dosage": "50mcg",
        "frequency": "once daily",
        "instructions": "Empty stomach, 30 minutes before breakfast",
        "times": ["07:00"],
    },
    {
        "raw_name": "Glycomet 500mg Tablet",
        "generic": "Metformin",
        "dosage": "500mg",
        "frequency": "twice daily",
        "instructions": "With meals — for gestational diabetes",
        "times": ["08:00", "20:00"],
    },
]

CONDITIONS = [
    ("gestational_diabetes", "Diagnosed at 24-week OGTT"),
    ("hypothyroidism", "Diagnosed pre-conception, dose increased in first trimester"),
]

ALLERGIES = [
    ("Sulfa drugs", "Widespread rash", "moderate", "Reacted to cotrimoxazole in 2019"),
]

SURGERIES = [("Appendectomy", "2019", "Apollo Hospital, Bengaluru", "Laparoscopic, uneventful")]

CONTACTS = [
    ("Arun Sharma", "husband", "+919876500023", True),
    ("Lakshmi Devi", "mother", "+919876500024", False),
]


def clear(db) -> bool:
    patient = db.query(Patient).filter(Patient.phone == PHONE).first()
    if not patient:
        return False
    # Adherence logs hang off schedules, which hang off medications, and none
    # of those cascade from Patient -- so they go first or they are orphaned.
    med_ids = [m.id for m in db.query(Medication).filter(Medication.patient_id == patient.id).all()]
    sched_ids = [
        s.id for s in db.query(Schedule).filter(Schedule.medication_id.in_(med_ids)).all()
    ] if med_ids else []
    if sched_ids:
        db.query(AdherenceLog).filter(AdherenceLog.schedule_id.in_(sched_ids)).delete(
            synchronize_session=False
        )
        db.query(Schedule).filter(Schedule.id.in_(sched_ids)).delete(synchronize_session=False)
    if med_ids:
        db.query(Medication).filter(Medication.id.in_(med_ids)).delete(synchronize_session=False)
    db.delete(patient)  # cascades conditions, allergies, surgeries, contacts, metrics
    db.commit()
    return True


def seed_vitals(db, patient_id: str) -> int:
    """
    Twelve weeks of antenatal monitoring. The numbers are deliberately
    unremarkable -- blood pressure comfortably normal, sugars controlled,
    steady weight gain -- because a demo profile that is already alarming
    leaves nothing for the safety check to reveal.
    """
    rng = random.Random(2026)
    now = datetime.now()
    count = 0

    for weeks_ago in range(12, 0, -1):
        when = now - timedelta(weeks=weeks_ago, hours=rng.randint(0, 6))

        # Blood pressure, checked at every antenatal visit for pre-eclampsia.
        systolic = 108 + rng.randint(-5, 7)
        diastolic = 70 + rng.randint(-4, 5)
        db.add(
            HealthMetric(
                patient_id=patient_id,
                metric_type="blood_pressure",
                value_primary=float(systolic),
                value_secondary=float(diastolic),
                unit="mmHg",
                recorded_at=when,
                note="Antenatal visit" if weeks_ago % 4 == 0 else None,
            )
        )
        count += 1

        # Fasting glucose, self-monitored for gestational diabetes. Drifts
        # down slightly over the series: metformin plus diet working.
        glucose = 104 - (12 - weeks_ago) * 0.9 + rng.uniform(-4, 4)
        db.add(
            HealthMetric(
                patient_id=patient_id,
                metric_type="blood_glucose",
                value_primary=round(glucose, 1),
                unit="mg/dL",
                context="fasting",
                recorded_at=when + timedelta(hours=1),
            )
        )
        count += 1

        # Weight: ~400g a week, the expected second-trimester gain.
        weight = 58.0 + (12 - weeks_ago) * 0.4 + rng.uniform(-0.2, 0.2)
        db.add(
            HealthMetric(
                patient_id=patient_id,
                metric_type="weight",
                value_primary=round(weight, 1),
                unit="kg",
                recorded_at=when + timedelta(hours=2),
            )
        )
        count += 1

    return count


def seed_adherence(db, schedules: list[Schedule], days: int = 30) -> tuple[int, int]:
    """
    Thirty days of dose history at roughly 85% -- good, not perfect, and above
    the 80% PDC threshold. A flawless record would make the adherence panel
    look decorative; a poor one would distract the demo onto a problem that
    isn't the point.
    """
    rng = random.Random(7)
    now = datetime.now()
    taken = total = 0

    for day_offset in range(days, 0, -1):
        day = (now - timedelta(days=day_offset)).date()
        for schedule in schedules:
            hour, minute = (int(x) for x in schedule.time_of_day.split(":"))
            scheduled_for = datetime.combine(day, datetime.min.time()).replace(
                hour=hour, minute=minute
            )
            total += 1
            roll = rng.random()
            if roll < 0.85:
                status = AdherenceStatus.TAKEN
                recorded = scheduled_for + timedelta(minutes=rng.randint(0, 45))
                taken += 1
            elif roll < 0.93:
                status = AdherenceStatus.SNOOZED
                recorded = scheduled_for + timedelta(minutes=rng.randint(30, 120))
            else:
                status = AdherenceStatus.SKIPPED
                recorded = scheduled_for
            db.add(
                AdherenceLog(
                    schedule_id=schedule.id,
                    scheduled_for=scheduled_for,
                    status=status,
                    recorded_at=recorded,
                )
            )
    return taken, total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clear", action="store_true", help="Remove the demo profile and exit.")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if args.clear:
            print("removed" if clear(db) else "nothing to remove")
            return

        # Rebuild from scratch so re-running is idempotent rather than
        # accumulating duplicate medicines each time.
        if clear(db):
            print("cleared previous demo profile")

        patient = Patient(
            name=NAME,
            phone=PHONE,
            date_of_birth="1998-04-12",
            preferred_language="en",
            gender="female",
            blood_group="B+",
            height_cm=158.0,
            weight_kg=62.4,
            organ_donor=False,
            primary_doctor_name="Dr. Meera Iyer (Obstetrics)",
            primary_doctor_phone="+918041234567",
            insurance_provider="Star Health",
            insurance_policy_no="SH-2024-778213",
            address="14, 3rd Cross, Jayanagar, Bengaluru 560011",
            emergency_notes=(
                f"{WEEKS_PREGNANT} weeks pregnant. Gestational diabetes on metformin. "
                "Hypothyroid on levothyroxine. Allergic to sulfa drugs."
            ),
            profile_completed=True,
            is_pregnant=True,
            pregnancy_due_date=DUE_DATE.isoformat(),
            is_breastfeeding=False,
        )
        db.add(patient)
        db.flush()

        for name, notes in CONDITIONS:
            db.add(Condition(patient_id=patient.id, name=name, notes=notes))
        for allergen, reaction, severity, notes in ALLERGIES:
            db.add(
                Allergy(
                    patient_id=patient.id,
                    allergen=allergen,
                    reaction=reaction,
                    severity=severity,
                    notes=notes,
                )
            )
        for name, year, hospital, notes in SURGERIES:
            db.add(
                Surgery(
                    patient_id=patient.id, name=name, year=year, hospital=hospital, notes=notes
                )
            )
        for name, rel, phone, is_primary in CONTACTS:
            db.add(
                EmergencyContact(
                    patient_id=patient.id,
                    name=name,
                    relationship_to_patient=rel,
                    phone=phone,
                    is_primary=is_primary,
                )
            )

        prescription = Prescription(
            patient_id=patient.id,
            file_path="demo/antenatal-visit.png",
            doctor_name="Dr. Meera Iyer",
            ocr_raw_text="(demo antenatal prescription)",
            ocr_confidence=0.97,
            ocr_provider="demo_seed",
            is_handwritten_guess=False,
            confirmation_status=ConfirmationStatus.CONFIRMED,
            confirmed_at=datetime.now() - timedelta(days=30),
            uploaded_at=datetime.now() - timedelta(days=30),
        )
        db.add(prescription)
        db.flush()

        # Link to curated drugs where one exists, so the medicine list shows
        # storage notes and drug class rather than a bare name.
        from app.models.models import DrugKnowledge

        schedules: list[Schedule] = []
        for spec in MEDICINES:
            drug = (
                db.query(DrugKnowledge)
                .filter(DrugKnowledge.generic_name == spec["generic"])
                .first()
            )
            medication = Medication(
                prescription_id=prescription.id,
                patient_id=patient.id,
                raw_name=spec["raw_name"],
                matched_drug_id=drug.id if drug else None,
                dosage=spec["dosage"],
                frequency=spec["frequency"],
                duration_days=None,
                route="oral",
                instructions=spec["instructions"],
                is_confirmed=True,
                created_at=datetime.now() - timedelta(days=30),
            )
            db.add(medication)
            db.flush()
            for time_of_day in spec["times"]:
                schedule = Schedule(medication_id=medication.id, time_of_day=time_of_day)
                db.add(schedule)
                db.flush()
                schedules.append(schedule)

        vitals = seed_vitals(db, patient.id)
        taken, total = seed_adherence(db, schedules)
        db.commit()

        write_patient_file(db, patient.id)

        print(f"created  : {NAME}, {PHONE}")
        print(f"pregnancy: {WEEKS_PREGNANT} weeks, due {DUE_DATE.isoformat()}")
        print(f"profile  : B+, 158cm, 62.4kg (BMI {62.4 / 1.58 ** 2:.1f})")
        print(f"medicines: {len(MEDICINES)} across {len(schedules)} daily reminder times")
        print(f"vitals   : {vitals} readings over 12 weeks")
        print(f"adherence: {taken}/{total} doses taken ({taken / total:.0%}) over 30 days")
        print(f"\nLog in with {PHONE} and OTP 000000.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
