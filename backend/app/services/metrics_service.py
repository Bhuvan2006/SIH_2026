"""
Health metric tracking: blood pressure, blood sugar, weight, steps.

Reference bands come from widely-published clinical guidance (ACC/AHA for
blood pressure, ADA for glucose, WHO for BMI). They are used ONLY to colour a
reading and name the band it falls in — never to diagnose. A single high
reading is not hypertension, and the UI says so; the value of the band is that
it turns "138/88" into something a patient can actually interpret.

Why this exists rather than a Google Fit sync
---------------------------------------------
Google closed the Fit REST API to new projects on 1 May 2024, and its
successors cover only Fitbit/Pixel Watch (Google Health API, plus a mandatory
Google security review) or require a native Android app (Health Connect).
Neither serves a web app whose users are mostly on ordinary Android phones.

Manual entry works for every user today, and for a medication-adherence app a
home BP or glucometer reading is more clinically useful than a step count. The
`source` column on HealthMetric keeps the door open: a device sync would write
the same rows and every chart below keeps working unchanged.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.models import AdherenceLog, AdherenceStatus, HealthMetric, Medication, Schedule

logger = logging.getLogger("arogya.metrics")

METRIC_TYPES = ("blood_pressure", "blood_glucose", "weight", "steps")

# (upper_bound_exclusive, band_label, tone). Last entry catches everything above.
BP_SYSTOLIC_BANDS = [
    (90, "Low", "warn"),
    (120, "Normal", "good"),
    (130, "Elevated", "warn"),
    (140, "High (stage 1)", "warn"),
    (999, "High (stage 2)", "bad"),
]
BP_DIASTOLIC_BANDS = [
    (60, "Low", "warn"),
    (80, "Normal", "good"),
    (90, "High (stage 1)", "warn"),
    (999, "High (stage 2)", "bad"),
]
GLUCOSE_FASTING_BANDS = [
    (70, "Low", "bad"),
    (100, "Normal", "good"),
    (126, "Above normal", "warn"),
    (999, "High", "bad"),
]
GLUCOSE_POST_MEAL_BANDS = [
    (70, "Low", "bad"),
    (140, "Normal", "good"),
    (200, "Above normal", "warn"),
    (999, "High", "bad"),
]
# CDC adult weight-status categories. Obesity is split into three classes
# because they are not the same clinical picture -- class 3 carries a
# different surgical and anaesthetic risk from class 1 -- and collapsing them
# into one "Obese" label threw that away.
#
# (upper_bound_exclusive, label, tone, range_text_for_display)
BMI_BANDS_FULL = [
    (18.5, "Underweight", "warn", "Below 18.5"),
    (25.0, "Healthy weight", "good", "18.5 – 24.9"),
    (30.0, "Overweight", "warn", "25.0 – 29.9"),
    (35.0, "Obese class 1", "bad", "30.0 – 34.9"),
    (40.0, "Obese class 2", "bad", "35.0 – 39.9"),
    (999, "Obese class 3", "bad", "40.0 and higher"),
]

# The (upper, label, tone) shape _band expects.
BMI_BANDS = [(upper, label, tone) for upper, label, tone, _ in BMI_BANDS_FULL]


def bmi_scale() -> list[dict]:
    """The whole CDC table, so the dashboard can show a patient where their
    own number sits rather than just naming their band in isolation."""
    return [
        {"range": text, "label": label, "tone": tone, "upper": upper}
        for upper, label, tone, text in BMI_BANDS_FULL
    ]


def bmi_range_text(bmi: float) -> str | None:
    for upper, _label, _tone, text in BMI_BANDS_FULL:
        if bmi < upper:
            return text
    return None


def _band(value: float, bands: list[tuple[float, str, str]]) -> tuple[str, str]:
    for upper, label, tone in bands:
        if value < upper:
            return label, tone
    return bands[-1][1], bands[-1][2]


@dataclass
class MetricSummary:
    metric_type: str
    latest_value: float | None
    latest_secondary: float | None
    latest_at: str | None
    band_label: str | None
    band_tone: str | None
    unit: str
    count: int
    average: float | None
    change_vs_previous: float | None
    series: list[dict]


def interpret(metric_type: str, primary: float, secondary: float | None, context: str | None):
    """Returns (band_label, tone) for a reading, or (None, None) if not banded."""
    if metric_type == "blood_pressure":
        s_label, s_tone = _band(primary, BP_SYSTOLIC_BANDS)
        if secondary is not None:
            d_label, d_tone = _band(secondary, BP_DIASTOLIC_BANDS)
            # Blood pressure is graded on whichever number is worse -- a normal
            # systolic doesn't make a diastolic of 95 fine.
            order = {"good": 0, "warn": 1, "bad": 2}
            if order[d_tone] > order[s_tone]:
                return d_label, d_tone
        return s_label, s_tone

    if metric_type == "blood_glucose":
        bands = GLUCOSE_FASTING_BANDS if (context or "") == "fasting" else GLUCOSE_POST_MEAL_BANDS
        return _band(primary, bands)

    return None, None


def bmi_for(
    height_cm: float | None,
    weight_kg: float | None,
    is_pregnant: bool = False,
):
    """
    Returns (bmi, band_label, band_tone).

    During pregnancy the number is still shown but is left UNBANDED. The BMI
    bands describe body composition, and a pregnant woman's weight includes
    the fetus, placenta and extra fluid, so the ratio no longer measures what
    the bands are about. ACOG and WHO both guide gestational weight gain from
    the woman's PRE-pregnancy BMI for exactly this reason.

    This matters beyond pedantry: a normally-built woman at 26 weeks crosses
    25.0 on schedule, and telling her she is "Overweight" is both wrong and
    the kind of thing a patient acts on.
    """
    if not height_cm or not weight_kg or height_cm <= 0:
        return None, None, None
    bmi = round(weight_kg / ((height_cm / 100) ** 2), 1)
    if is_pregnant:
        return bmi, None, None
    label, tone = _band(bmi, BMI_BANDS)
    return bmi, label, tone


def summarise(
    db: Session, patient_id: str, metric_type: str, days: int = 90
) -> MetricSummary:
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(HealthMetric)
        .filter(
            HealthMetric.patient_id == patient_id,
            HealthMetric.metric_type == metric_type,
            HealthMetric.recorded_at >= since,
        )
        .order_by(HealthMetric.recorded_at.asc())
        .all()
    )

    unit = {
        "blood_pressure": "mmHg",
        "blood_glucose": "mg/dL",
        "weight": "kg",
        "steps": "steps",
    }.get(metric_type, "")

    if not rows:
        return MetricSummary(
            metric_type=metric_type,
            latest_value=None,
            latest_secondary=None,
            latest_at=None,
            band_label=None,
            band_tone=None,
            unit=unit,
            count=0,
            average=None,
            change_vs_previous=None,
            series=[],
        )

    latest = rows[-1]
    label, tone = interpret(metric_type, latest.value_primary, latest.value_secondary, latest.context)
    avg = round(sum(r.value_primary for r in rows) / len(rows), 1)
    change = (
        round(latest.value_primary - rows[-2].value_primary, 1) if len(rows) >= 2 else None
    )

    return MetricSummary(
        metric_type=metric_type,
        latest_value=latest.value_primary,
        latest_secondary=latest.value_secondary,
        latest_at=latest.recorded_at.isoformat() if latest.recorded_at else None,
        band_label=label,
        band_tone=tone,
        unit=unit,
        count=len(rows),
        average=avg,
        change_vs_previous=change,
        series=[
            {
                "date": r.recorded_at.date().isoformat() if r.recorded_at else None,
                "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
                "primary": r.value_primary,
                "secondary": r.value_secondary,
                "context": r.context,
                "source": r.source,
            }
            for r in rows
        ],
    )


def adherence_overlay(db: Session, patient_id: str, days: int = 90) -> list[dict]:
    """
    Daily dose-adherence percentage, for plotting underneath a vitals chart.

    This is the pairing nothing else in the app can show: whether readings
    drift while doses are being missed. Presented as two series on one
    timeline, and described in the UI as something to discuss with a doctor --
    never as proof that one caused the other.
    """
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(AdherenceLog)
        .join(Schedule, AdherenceLog.schedule_id == Schedule.id)
        .join(Medication, Schedule.medication_id == Medication.id)
        .filter(Medication.patient_id == patient_id, AdherenceLog.scheduled_for >= since)
        .all()
    )

    by_day: dict[str, dict[str, int]] = {}
    for log in rows:
        key = log.scheduled_for.date().isoformat()
        b = by_day.setdefault(key, {"expected": 0, "taken": 0})
        b["expected"] += 1
        if log.status == AdherenceStatus.TAKEN:
            b["taken"] += 1

    return [
        {
            "date": day,
            "percent": round(b["taken"] / b["expected"] * 100, 1) if b["expected"] else 0.0,
        }
        for day, b in sorted(by_day.items())
    ]
