"""
Per-patient data file.

Every patient gets one JSON file under `app/patient_data/{patient_id}.json`
holding their whole picture: profile, blood group, allergies, conditions,
emergency contacts, confirmed medicines (from their prescriptions), and
reminder schedule.

Why a file rather than just querying the DB in the chatbot:
  * It is the single, inspectable artifact the RAG layer reads, so what the
    chatbot can see about a patient is auditable -- you can open the file and
    know exactly what was in context.
  * It keeps patient context assembly in one place instead of scattering
    joins through the chat request path.
  * It gives a natural export/erasure unit for DPDP retention work later
    (delete the row, delete the file).

The file is rewritten whenever the underlying data changes (profile save,
prescription confirm, allergy/contact edits) -- see `write_patient_file`.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.models import (
    Allergy,
    Condition,
    DrugKnowledge,
    EmergencyContact,
    HealthMetric,
    Surgery,
    Medication,
    Patient,
    Prescription,
    Schedule,
)

logger = logging.getLogger("arogya.patient_file")

PATIENT_DATA_DIR = Path(__file__).resolve().parent.parent / "patient_data"
PATIENT_DATA_DIR.mkdir(exist_ok=True)


def patient_file_path(patient_id: str) -> Path:
    return PATIENT_DATA_DIR / f"{patient_id}.json"


def build_patient_record(db: Session, patient_id: str) -> dict | None:
    """Assembles the full patient picture as a plain dict."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        return None

    allergies = db.query(Allergy).filter(Allergy.patient_id == patient_id).all()
    conditions = db.query(Condition).filter(Condition.patient_id == patient_id).all()
    contacts = db.query(EmergencyContact).filter(EmergencyContact.patient_id == patient_id).all()

    medications = (
        db.query(Medication)
        .filter(Medication.patient_id == patient_id, Medication.is_confirmed == True)  # noqa: E712
        .all()
    )

    med_entries = []
    for med in medications:
        schedules = [
            s.time_of_day
            for s in db.query(Schedule)
            .filter(Schedule.medication_id == med.id, Schedule.active == True)  # noqa: E712
            .all()
        ]
        storage = None
        drug_class = None
        if med.matched_drug_id:
            drug = db.query(DrugKnowledge).filter(DrugKnowledge.id == med.matched_drug_id).first()
            if drug:
                storage = drug.storage_instructions
                drug_class = drug.drug_class

        med_entries.append(
            {
                "name": med.raw_name,
                "matched_generic_name": med.matched_drug.generic_name if med.matched_drug else None,
                "drug_class": drug_class,
                "dosage": med.dosage,
                "frequency": med.frequency,
                "duration_days": med.duration_days,
                "route": med.route,
                "instructions": med.instructions,
                "reminder_times": sorted(schedules),
                "storage_instructions": storage,
                "started_on": med.created_at.isoformat() if med.created_at else None,
            }
        )

    prescriptions = (
        db.query(Prescription)
        .filter(Prescription.patient_id == patient_id)
        .order_by(Prescription.uploaded_at.desc())
        .all()
    )

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "patient_id": patient.id,
        "profile": {
            "name": patient.name,
            "phone": patient.phone,
            "date_of_birth": patient.date_of_birth,
            "gender": patient.gender,
            "blood_group": patient.blood_group,
            "height_cm": patient.height_cm,
            "weight_kg": patient.weight_kg,
            "organ_donor": patient.organ_donor,
            "implants_devices": patient.implants_devices,
            "address": patient.address,
            "preferred_language": patient.preferred_language,
            "primary_doctor": {
                "name": patient.primary_doctor_name,
                "phone": patient.primary_doctor_phone,
            },
            "insurance": {
                "provider": patient.insurance_provider,
                "policy_no": patient.insurance_policy_no,
            },
            "emergency_notes": patient.emergency_notes,
            "is_pregnant": patient.is_pregnant,
            "pregnancy_due_date": patient.pregnancy_due_date,
            "is_breastfeeding": patient.is_breastfeeding,
        },
        "allergies": [
            {
                "allergen": a.allergen,
                "reaction": a.reaction,
                "severity": a.severity,
                "notes": a.notes,
            }
            for a in allergies
        ],
        "conditions": [
            {"name": c.name, "diagnosed_date": c.diagnosed_date, "notes": c.notes} for c in conditions
        ],
        "emergency_contacts": [
            {
                "name": c.name,
                "relationship": c.relationship_to_patient,
                "phone": c.phone,
                "is_primary": c.is_primary,
            }
            for c in contacts
        ],
        "surgeries": [
            {"name": s.name, "year": s.year, "hospital": s.hospital, "notes": s.notes}
            for s in db.query(Surgery).filter(Surgery.patient_id == patient_id).all()
        ],
        "recent_readings": [
            {
                "type": m.metric_type,
                "value": m.value_primary,
                "value_secondary": m.value_secondary,
                "unit": m.unit,
                "context": m.context,
                "recorded_at": m.recorded_at.isoformat() if m.recorded_at else None,
            }
            for m in (
                db.query(HealthMetric)
                .filter(HealthMetric.patient_id == patient_id)
                .order_by(HealthMetric.recorded_at.desc())
                .limit(20)
                .all()
            )
        ],
        "current_medications": med_entries,
        "prescriptions": [
            {
                "uploaded_at": p.uploaded_at.isoformat() if p.uploaded_at else None,
                "doctor_name": p.doctor_name,
                "status": p.confirmation_status.value if p.confirmation_status else None,
                "ocr_provider": p.ocr_provider,
            }
            for p in prescriptions
        ],
    }


def write_patient_file(db: Session, patient_id: str) -> Path | None:
    """Rebuilds and persists the patient's data file. Never raises."""
    try:
        record = build_patient_record(db, patient_id)
        if record is None:
            return None
        path = patient_file_path(patient_id)
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
    except Exception:  # noqa: BLE001
        # Writing this file is a convenience for the chatbot; failing to
        # write it must never break the request that triggered it.
        logger.exception("Failed writing patient data file for %s", patient_id)
        return None


def read_patient_file(patient_id: str) -> dict | None:
    path = patient_file_path(patient_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.exception("Failed reading patient data file for %s", patient_id)
        return None


def delete_patient_file(patient_id: str) -> None:
    path = patient_file_path(patient_id)
    if path.exists():
        path.unlink()


def render_patient_context(record: dict) -> str:
    """
    Flattens the patient record into a compact text block for the chatbot's
    grounding context. Only includes sections that actually have data, so an
    empty profile doesn't fill the prompt with "None".
    """
    if not record:
        return ""

    p = record.get("profile", {}) or {}
    lines: list[str] = ["[THIS PATIENT'S OWN RECORD]"]

    ident = []
    if p.get("name"):
        ident.append(f"Name: {p['name']}")
    if p.get("date_of_birth"):
        ident.append(f"DOB: {p['date_of_birth']}")
    if p.get("gender"):
        ident.append(f"Gender: {p['gender']}")
    if p.get("blood_group"):
        ident.append(f"Blood group: {p['blood_group']}")
    if ident:
        lines.append("  " + " | ".join(ident))

    if p.get("implants_devices"):
        lines.append(f"  Implants/devices: {p['implants_devices']}")
    if p.get("emergency_notes"):
        lines.append(f"  Notes: {p['emergency_notes']}")

    allergies = record.get("allergies") or []
    if allergies:
        lines.append("  Allergies:")
        for a in allergies:
            bits = [a.get("allergen") or "?"]
            if a.get("severity") and a["severity"] != "unknown":
                bits.append(f"severity: {a['severity']}")
            if a.get("reaction"):
                bits.append(f"reaction: {a['reaction']}")
            lines.append("    - " + ", ".join(bits))

    conditions = record.get("conditions") or []
    if conditions:
        lines.append("  Conditions: " + ", ".join(c.get("name", "?") for c in conditions))

    if p.get("is_pregnant"):
        due = f" (due {p['pregnancy_due_date']})" if p.get("pregnancy_due_date") else ""
        lines.append(f"  PREGNANT{due} — apply pregnancy-safety rules to every medicine question.")
    if p.get("is_breastfeeding"):
        lines.append("  Breastfeeding — check medicines for lactation safety.")

    surgeries = record.get("surgeries") or []
    if surgeries:
        lines.append("  Past surgeries: " + ", ".join(
            f"{s['name']}" + (f" ({s['year']})" if s.get("year") else "") for s in surgeries))

    readings = record.get("recent_readings") or []
    if readings:
        lines.append("  Recent readings (most recent first):")
        for r in readings[:8]:
            val = f"{r['value']}"
            if r.get("value_secondary"):
                val += f"/{r['value_secondary']}"
            bits = [r["type"].replace("_", " "), val, r.get("unit") or ""]
            if r.get("context"):
                bits.append(f"({r['context']})")
            if r.get("recorded_at"):
                bits.append(f"on {r['recorded_at'][:10]}")
            lines.append("    - " + " ".join(b for b in bits if b))

    meds = record.get("current_medications") or []
    if meds:
        lines.append("  Current medicines (patient-confirmed):")
        for m in meds:
            bits = [m.get("matched_generic_name") or m.get("name") or "?"]
            if m.get("dosage"):
                bits.append(m["dosage"])
            if m.get("frequency"):
                bits.append(m["frequency"])
            if m.get("reminder_times"):
                bits.append("at " + ", ".join(m["reminder_times"]))
            if m.get("instructions"):
                bits.append(f"({m['instructions']})")
            lines.append("    - " + " ".join(bits))
            if m.get("storage_instructions"):
                lines.append(f"      storage: {m['storage_instructions']}")

    return "\n".join(lines)
