"""
Health metric endpoints: log a reading, list readings, and get the dashboard
summary with the adherence overlay.
"""
from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_patient
from app.db.database import get_db
from app.models.models import Condition, HealthMetric, Patient
from app.schemas.schemas import HealthMetricIn, HealthMetricOut
from app.services.metrics_service import (
    METRIC_TYPES,
    adherence_overlay,
    bmi_for,
    interpret,
    summarise,
)
from app.services.patient_file_service import write_patient_file

router = APIRouter(prefix="/metrics", tags=["health-metrics"])

# Which metrics to surface for which conditions. Showing a diabetic patient a
# glucose card and a hypertensive patient a BP card beats showing everyone
# every field -- an empty chart the user has no reason to fill is noise.
CONDITION_METRICS = {
    "diabetes_type_1": "blood_glucose",
    "diabetes_type_2": "blood_glucose",
    "hypertension": "blood_pressure",
    "ckd": "blood_pressure",
    "dyslipidemia": "weight",
}


@router.post("", response_model=HealthMetricOut)
def add_metric(
    payload: HealthMetricIn,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    if payload.metric_type not in METRIC_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"metric_type must be one of {', '.join(METRIC_TYPES)}",
        )
    if payload.metric_type == "blood_pressure" and payload.value_secondary is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Blood pressure needs both systolic and diastolic values.",
        )

    metric = HealthMetric(
        patient_id=patient.id,
        metric_type=payload.metric_type,
        value_primary=payload.value_primary,
        value_secondary=payload.value_secondary,
        unit=payload.unit,
        context=payload.context,
        note=payload.note,
        recorded_at=payload.recorded_at or datetime.utcnow(),
        source="manual",
    )
    db.add(metric)
    db.commit()
    db.refresh(metric)

    # Keep the chatbot's view of the patient current.
    write_patient_file(db, patient.id)

    label, tone = interpret(
        metric.metric_type, metric.value_primary, metric.value_secondary, metric.context
    )
    out = HealthMetricOut.model_validate(metric, from_attributes=True)
    out.band_label = label
    out.band_tone = tone
    return out


@router.get("", response_model=list[HealthMetricOut])
def list_metrics(
    metric_type: str | None = None,
    limit: int = 100,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    q = db.query(HealthMetric).filter(HealthMetric.patient_id == patient.id)
    if metric_type:
        q = q.filter(HealthMetric.metric_type == metric_type)
    rows = q.order_by(HealthMetric.recorded_at.desc()).limit(min(limit, 500)).all()

    out = []
    for m in rows:
        item = HealthMetricOut.model_validate(m, from_attributes=True)
        item.band_label, item.band_tone = interpret(
            m.metric_type, m.value_primary, m.value_secondary, m.context
        )
        out.append(item)
    return out


@router.delete("/{metric_id}")
def delete_metric(
    metric_id: str,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    metric = (
        db.query(HealthMetric)
        .filter(HealthMetric.id == metric_id, HealthMetric.patient_id == patient.id)
        .first()
    )
    if not metric:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reading not found")
    db.delete(metric)
    db.commit()
    write_patient_file(db, patient.id)
    return {"deleted": metric_id}


@router.get("/summary")
def metrics_summary(
    days: int = 90,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    """Dashboard payload: which metrics matter for this patient, their trends,
    and daily adherence on the same timeline for comparison."""
    window = max(7, min(days, 365))

    conditions = [
        c.name for c in db.query(Condition).filter(Condition.patient_id == patient.id).all()
    ]
    relevant = {CONDITION_METRICS[c] for c in conditions if c in CONDITION_METRICS}
    # Weight is universally useful and needs no condition to justify it.
    relevant.add("weight")

    # Anything already logged stays visible even if the condition was removed.
    logged = {
        row[0]
        for row in db.query(HealthMetric.metric_type)
        .filter(HealthMetric.patient_id == patient.id)
        .distinct()
        .all()
    }
    show = sorted(relevant | logged)

    is_pregnant = bool(getattr(patient, "is_pregnant", False))
    bmi, bmi_label, bmi_tone = bmi_for(patient.height_cm, patient.weight_kg, is_pregnant)

    return {
        "window_days": window,
        "suggested_metrics": show,
        "metrics": {m: asdict(summarise(db, patient.id, m, window)) for m in show},
        "adherence_overlay": adherence_overlay(db, patient.id, window),
        "bmi": {
            "value": bmi,
            "band_label": bmi_label,
            "band_tone": bmi_tone,
            # The UI shows this instead of a band during pregnancy, rather
            # than leaving an unexplained blank where a rating used to be.
            "note": (
                "BMI categories don't apply during pregnancy — weight gain is expected. "
                "Your doctor tracks gain against your pre-pregnancy weight."
                if is_pregnant
                else None
            ),
        },
        "disclaimer": (
            "Reference ranges are general guidance, not a diagnosis. A single reading outside a "
            "range is common and often not meaningful — patterns over time are what matter, and "
            "they are for your doctor to interpret."
        ),
    }
