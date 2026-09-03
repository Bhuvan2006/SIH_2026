"""
A clinical summary of a patient, for the doctor about to see them.

The point is the two minutes before a consultation. A doctor opening a record
cold has to read allergies, conditions, surgeries, a medicine list, months of
vitals and an adherence history to work out what actually matters today. This
assembles the facts that change management -- and says plainly when a fact is
missing rather than letting silence read as "nothing to report".

Structure over prose
--------------------
The deterministic part is computed here, not written by a model: allergies,
pregnancy, banned or contraindicated medicines, adherence, vitals out of band.
Those are facts, and a doctor must be able to trust them exactly. The model is
given those facts and asked only to write the narrative paragraph on top.

When the model is unavailable -- no key, quota exhausted, a stalled call -- the
summary still renders from the structured half. A doctor gets slightly drier
text, never a blank page.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.models import (
    AdherenceLog,
    AdherenceStatus,
    Allergy,
    Appointment,
    Condition,
    DrugKnowledge,
    HealthMetric,
    Medication,
    Patient,
    Schedule,
    Surgery,
)
from app.services import metrics_service, safety_service

logger = logging.getLogger("arogya.summary")

# Same bounds as the chatbot: a stalled model must not hold the request open
# while a doctor waits with a patient in front of them.
GEMINI_CALL_TIMEOUT_MS = 20_000

SYSTEM_PROMPT = """You are writing a handover note for a doctor who is about to see this patient.

Write 3-5 short sentences. Lead with whatever changes management today.

Rules:
- Use ONLY the facts given. Never add a diagnosis, drug, or number that is not there.
- Do not repeat the structured lists back; the doctor sees those beside your text.
- Name gaps explicitly ("no BP recorded since March") rather than staying silent about them.
- No greeting, no sign-off, no headings, no bullet points. Plain prose.
- Never recommend a prescription change. You are summarising, not advising."""


@dataclass
class SummaryFact:
    label: str
    detail: str
    tone: str = "neutral"   # neutral | good | warn | bad


@dataclass
class PatientSummary:
    patient_id: str
    patient_name: str | None
    age_years: int | None
    narrative: str
    narrative_source: str                      # "model" | "deterministic"
    highlights: list[SummaryFact] = field(default_factory=list)
    medicines: list[dict] = field(default_factory=list)
    safety_flags: list[dict] = field(default_factory=list)
    vitals: list[dict] = field(default_factory=list)
    adherence: dict | None = None
    last_seen: str | None = None
    generated_at: str = ""


# Safety-flag titles are written in the second person for the patient who is
# about to swallow the tablet. The doctor's view needs the same fact stated
# clinically, so these rewrite the opening rather than duplicating the rules.
_CLINICAL_PHRASING = [
    ("You have a recorded allergy to", "Recorded allergy:"),
    ("You may not be able to take this", "May be contraindicated"),
    ("You are already taking this", "Already prescribed"),
    ("This medicine appears to be", "Medicine is"),
    ("This medicine is", "Medicine is"),
    ("This combination is", "Combination is"),
    ("Not normally used in pregnancy — and your profile says you are pregnant",
     "Contraindicated in pregnancy"),
    ("Not normally used in pregnancy", "Contraindicated in pregnancy"),
    ("May interact with", "Interacts with"),
]


def _clinical_phrasing(title: str) -> str:
    for patient_phrasing, clinical in _CLINICAL_PHRASING:
        if title.startswith(patient_phrasing):
            return clinical + title[len(patient_phrasing):]
    return title


def _age(dob: str | None) -> int | None:
    if not dob:
        return None
    try:
        born = datetime.strptime(dob, "%Y-%m-%d").date()
    except ValueError:
        return None
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _adherence(db: Session, patient_id: str, days: int = 30) -> dict | None:
    """Doses taken vs expected. Adherence is the single most useful thing a
    doctor can know before blaming a drug for not working."""
    med_ids = [m.id for m in db.query(Medication).filter(Medication.patient_id == patient_id).all()]
    if not med_ids:
        return None
    schedule_ids = [
        s.id for s in db.query(Schedule).filter(Schedule.medication_id.in_(med_ids)).all()
    ]
    if not schedule_ids:
        return None

    logs = (
        db.query(AdherenceLog)
        .filter(AdherenceLog.schedule_id.in_(schedule_ids))
        .order_by(AdherenceLog.scheduled_for.desc())
        .limit(days * max(1, len(schedule_ids)))
        .all()
    )
    if not logs:
        return None
    taken = sum(1 for log in logs if log.status == AdherenceStatus.TAKEN)
    percent = round(taken / len(logs) * 100, 1)
    return {
        "percent": percent,
        "doses_taken": taken,
        "doses_expected": len(logs),
        # 80% is the Pharmacy Quality Alliance threshold below which a chronic
        # medicine stops reliably working.
        "below_target": percent < 80.0,
    }


def build(db: Session, patient: Patient, doctor_id: str | None = None) -> PatientSummary:
    allergies = db.query(Allergy).filter(Allergy.patient_id == patient.id).all()
    conditions = db.query(Condition).filter(Condition.patient_id == patient.id).all()
    surgeries = db.query(Surgery).filter(Surgery.patient_id == patient.id).all()
    medications = db.query(Medication).filter(Medication.patient_id == patient.id).all()

    highlights: list[SummaryFact] = []

    if patient.is_pregnant:
        detail = "Pregnant"
        if patient.pregnancy_due_date:
            detail += f", due {patient.pregnancy_due_date}"
        detail += ". Check every prescription against pregnancy contraindications."
        highlights.append(SummaryFact("Pregnancy", detail, "warn"))
    if patient.is_breastfeeding:
        highlights.append(SummaryFact("Breastfeeding", "Check drug transfer into milk.", "warn"))

    for a in allergies:
        tone = "bad" if (a.severity or "").lower() in ("severe", "anaphylaxis") else "warn"
        bits = [b for b in [a.reaction, a.severity] if b]
        highlights.append(
            SummaryFact(f"Allergy: {a.allergen}", ", ".join(bits) or "No detail recorded", tone)
        )

    if patient.blood_group:
        highlights.append(SummaryFact("Blood group", patient.blood_group))
    else:
        # A missing blood group is worth flagging, not silently omitting: it is
        # the field an emergency clinician reaches for first.
        highlights.append(SummaryFact("Blood group", "Not recorded", "warn"))

    if patient.implants_devices:
        highlights.append(SummaryFact("Implants / devices", patient.implants_devices, "warn"))

    # Run the same five-check screening the patient's own prescription review
    # uses, so the doctor sees exactly what the patient was shown.
    safety_flags: list[dict] = []
    if medications:
        screened = safety_service.screen_prescription(
            db,
            patient.id,
            [(m.raw_name, m.matched_drug_id) for m in medications],
        )
        seen_titles: set[str] = set()
        for index, result in enumerate(screened):
            source_medicine = (
                medications[index].raw_name if index < len(medications) else None
            )
            for flag in result.flags:
                # The screening compares a prescription against the patient's
                # CURRENT medicines. Here the list being screened IS that list,
                # so every drug matches itself and reports "already taking this"
                # -- true, useless, and it buries the real flags.
                if flag.kind == "duplicate":
                    continue
                # The same interaction is raised once from each side of the
                # pair; a doctor needs to see it once.
                key = f"{flag.kind}|{flag.title}|{flag.detail}|{source_medicine}"
                if key in seen_titles:
                    continue
                seen_titles.add(key)
                safety_flags.append(
                    {
                        "kind": flag.kind,
                        "severity": flag.severity,
                        # Flag text is written for the patient ("You have a
                        # recorded allergy to..."). A doctor is reading this.
                        "title": _clinical_phrasing(flag.title),
                        "detail": flag.detail,
                        "source": flag.source,
                        # WHICH medicine raised it. Without this, two genuine
                        # interactions -- calcium and iron both reducing
                        # levothyroxine absorption -- render as the same line
                        # twice and look like a duplicate bug.
                        "medicine": source_medicine,
                    }
                )

    medicines = []
    for m in medications:
        generic = None
        if m.matched_drug_id:
            drug = db.query(DrugKnowledge).filter(DrugKnowledge.id == m.matched_drug_id).first()
            generic = drug.generic_name if drug else None
        medicines.append(
            {
                "id": m.id,
                "raw_name": m.raw_name,
                "generic_name": generic,
                "dosage": m.dosage,
                "frequency": m.frequency,
                "instructions": m.instructions,
                # False means the medicine is not in the clinical database, so
                # no contraindication check ran on it at all.
                "has_safety_data": m.matched_drug_id is not None,
            }
        )

    vitals = []
    for metric_type in ("blood_pressure", "blood_glucose", "weight"):
        summary = metrics_service.summarise(db, patient.id, metric_type, days=180)
        if summary.count == 0:
            continue
        vitals.append(
            {
                "metric": metric_type,
                "latest_value": summary.latest_value,
                "latest_secondary": summary.latest_secondary,
                "unit": summary.unit,
                "band_label": summary.band_label,
                "band_tone": summary.band_tone,
                "latest_at": summary.latest_at,
                "count": summary.count,
                "average": summary.average,
            }
        )
        if summary.band_tone in ("warn", "bad"):
            value = f"{summary.latest_value}"
            if summary.latest_secondary:
                value += f"/{summary.latest_secondary}"
            highlights.append(
                SummaryFact(
                    metric_type.replace("_", " ").title(),
                    f"{value} {summary.unit} — {summary.band_label}",
                    summary.band_tone,
                )
            )

    adherence = _adherence(db, patient.id)
    if adherence and adherence["below_target"]:
        highlights.append(
            SummaryFact(
                "Adherence",
                f"{adherence['percent']}% of doses taken in the last 30 days — below the 80% "
                "level at which a long-term medicine reliably works.",
                "bad",
            )
        )

    last_appointment = (
        db.query(Appointment)
        .filter(Appointment.patient_id == patient.id, Appointment.status == "completed")
        .order_by(Appointment.date.desc())
        .first()
    )

    facts = {
        "name": patient.name,
        "age": _age(patient.date_of_birth),
        "gender": patient.gender,
        "pregnant": bool(patient.is_pregnant),
        "pregnancy_due_date": patient.pregnancy_due_date,
        "breastfeeding": bool(patient.is_breastfeeding),
        "blood_group": patient.blood_group,
        "conditions": [c.name for c in conditions],
        "allergies": [
            {"allergen": a.allergen, "reaction": a.reaction, "severity": a.severity}
            for a in allergies
        ],
        "surgeries": [{"name": s.name, "year": s.year} for s in surgeries],
        "medicines": [
            {"name": m["generic_name"] or m["raw_name"], "dose": m["dosage"], "frequency": m["frequency"]}
            for m in medicines
        ],
        "safety_flags": [{"severity": f["severity"], "title": f["title"]} for f in safety_flags],
        "vitals": vitals,
        "adherence": adherence,
        "last_completed_visit": last_appointment.date if last_appointment else None,
    }

    narrative, source = _narrative(facts, highlights)

    return PatientSummary(
        patient_id=patient.id,
        patient_name=patient.name,
        age_years=facts["age"],
        narrative=narrative,
        narrative_source=source,
        highlights=highlights,
        medicines=medicines,
        safety_flags=safety_flags,
        vitals=vitals,
        adherence=adherence,
        last_seen=last_appointment.date if last_appointment else None,
        generated_at=datetime.utcnow().isoformat(),
    )


def _deterministic_narrative(facts: dict, highlights: list[SummaryFact]) -> str:
    """The fallback, and the safety net. Never empty."""
    bits: list[str] = []

    who = facts.get("name") or "This patient"
    age = facts.get("age")
    gender = facts.get("gender")
    opener = who
    if age and gender:
        opener += f", {age}, {gender}"
    elif age:
        opener += f", {age}"
    conditions = facts.get("conditions") or []
    if conditions:
        opener += ", with " + ", ".join(c.replace("_", " ") for c in conditions)
    bits.append(opener + ".")

    if facts.get("pregnant"):
        due = facts.get("pregnancy_due_date")
        bits.append(f"Pregnant{f', due {due}' if due else ''}.")

    medicines = facts.get("medicines") or []
    bits.append(
        f"On {len(medicines)} regular medicine{'s' if len(medicines) != 1 else ''}."
        if medicines
        else "No regular medicines recorded."
    )

    critical = [f for f in (facts.get("safety_flags") or []) if f["severity"] == "critical"]
    if critical:
        bits.append(
            f"{len(critical)} critical safety flag"
            f"{'s' if len(critical) != 1 else ''} on the current medicines."
        )

    adherence = facts.get("adherence")
    if adherence:
        bits.append(f"Adherence {adherence['percent']}% over the last 30 days.")

    last = facts.get("last_completed_visit")
    bits.append(f"Last completed visit {last}." if last else "No completed visit on record.")

    return " ".join(bits)


def _narrative(facts: dict, highlights: list[SummaryFact]) -> tuple[str, str]:
    settings = get_settings()
    fallback = _deterministic_narrative(facts, highlights)

    if settings.LLM_PROVIDER != "google" or not settings.GOOGLE_API_KEY:
        return fallback, "deterministic"

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return fallback, "deterministic"

    models = [settings.GEMINI_MODEL] + [
        m.strip() for m in (settings.GEMINI_FALLBACK_MODELS or "").split(",") if m.strip()
    ]
    client = genai.Client(
        api_key=settings.GOOGLE_API_KEY,
        http_options=types.HttpOptions(timeout=GEMINI_CALL_TIMEOUT_MS),
    )
    # Gemini 3.x spends part of max_output_tokens on hidden reasoning before
    # any visible text. At 900 the reasoning alone consumed most of it and the
    # narrative came back cut off mid-sentence ("She has a").
    config_kwargs = {
        "system_instruction": SYSTEM_PROMPT,
        "max_output_tokens": 2500,
        "temperature": 0.2,
    }
    try:
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="low")
    except Exception:  # noqa: BLE001
        pass

    prompt = "Patient facts as JSON:\n" + json.dumps(facts, indent=2, default=str)

    for model_name in models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                config=types.GenerateContentConfig(**config_kwargs),
            )
            text = (response.text or "").strip()
            finish = (
                str(getattr(response.candidates[0], "finish_reason", ""))
                if response.candidates
                else ""
            )
            # A truncated handover note is worse than a plain one: it stops
            # mid-clause and the doctor cannot tell what was left out.
            if text and not finish.endswith("MAX_TOKENS"):
                return text, "model"
            if text:
                logger.warning("Summary from %s hit MAX_TOKENS; using computed text", model_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Summary model %s failed (%s)", model_name, type(exc).__name__)
            continue

    return fallback, "deterministic"
