"""
Health awareness hub: home-equipment guides, video topics, activity ideas,
and nearby places to be active.

Content is curated JSON (app/data/wellness_content.json) rather than generated,
for the same reason the drug knowledge base is: this is health guidance shown
to patients, so every card needs to trace to a source a human can check.

On videos: we deliberately do NOT hard-code YouTube video IDs. A video ID can
be deleted, re-uploaded, or replaced with something we never reviewed, and an
unreviewed medical video embedded in a health app is a real risk. Each topic
instead resolves to a search on an authoritative channel, and the schema keeps
an optional `video_id` so a human can pin a specific reviewed video later.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import get_current_patient
from app.db.database import get_db
from app.models.models import Condition, HealthEvent, Patient
from app.schemas.schemas import HealthEventIn, HealthEventOut

logger = logging.getLogger("arogya.wellness")

router = APIRouter(prefix="/wellness", tags=["wellness"])

# This module lives in app/api/routers/, so the data directory is three
# levels up (app/), not two.
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# Places types that count as "somewhere to be active". Parks lead deliberately:
# they're free, which matters for the population this app serves.
FITNESS_PLACE_TYPES = ["park", "gym", "yoga_studio", "sports_complex", "swimming_pool"]


def _load_content() -> dict:
    try:
        return json.loads((DATA_DIR / "wellness_content.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.exception("Could not load wellness_content.json")
        return {}


def _youtube_url(topic: dict) -> str:
    """A pinned video if one was reviewed, otherwise a search on the topic."""
    if topic.get("video_id"):
        return f"https://www.youtube.com/watch?v={topic['video_id']}"
    return f"https://www.youtube.com/results?search_query={quote_plus(topic.get('search', topic.get('title', '')))}"


@router.get("")
def wellness_hub(
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    """Awareness content, prioritised by the patient's own conditions."""
    content = _load_content()

    conditions = {
        c.name for c in db.query(Condition).filter(Condition.patient_id == patient.id).all()
    }

    # Surface the topics that match this patient's conditions first. Someone
    # with diabetes should not have to scroll past four unrelated cards to
    # reach the one about blood sugar.
    priority: dict[str, list[str]] = {
        "diabetes_type_1": ["diabetes_basics", "diet_india", "glucometer"],
        "diabetes_type_2": ["diabetes_basics", "diet_india", "glucometer"],
        "hypertension": ["bp_basics", "diet_india", "bp_monitor"],
        "ckd": ["bp_basics", "bp_monitor"],
        "asthma": ["pulse_oximeter"],
        "dyslipidemia": ["activity", "diet_india"],
    }
    relevant_ids: set[str] = set()
    for c in conditions:
        relevant_ids.update(priority.get(c, []))

    def rank(items: list[dict]) -> list[dict]:
        tagged = [{**i, "recommended": i.get("id") in relevant_ids} for i in items]
        return sorted(tagged, key=lambda i: not i["recommended"])

    topics = [
        {**t, "youtube_url": _youtube_url(t), "video_id": t.get("video_id")}
        for t in content.get("video_topics", [])
    ]

    return {
        "equipment_guides": rank(content.get("equipment_guides", [])),
        "video_topics": rank(topics),
        "activity_ideas": content.get("activity_ideas", []),
        "awareness": content.get("awareness", []),
        "personalised_for": sorted(conditions),
        "disclaimer": (
            "General health education, not medical advice. Techniques here help you take a "
            "reading correctly — what the reading means for you is a question for your doctor."
        ),
    }


EVENT_TYPES = ("walk", "yoga", "screening", "talk", "camp", "other")


def _event_out(event: HealthEvent, patient_id: str) -> HealthEventOut:
    out = HealthEventOut.model_validate(event, from_attributes=True)
    out.is_mine = event.created_by == patient_id
    return out


@router.get("/events", response_model=list[HealthEventOut])
def list_events(
    include_past: bool = False,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    """
    Community events, soonest first.

    Past events are hidden by default — a noticeboard full of last month's
    camps is worse than an empty one.
    """
    q = db.query(HealthEvent).filter(HealthEvent.is_cancelled == False)  # noqa: E712
    if not include_past:
        q = q.filter(HealthEvent.starts_at >= datetime.utcnow() - timedelta(hours=6))
    events = q.order_by(HealthEvent.starts_at.asc()).limit(50).all()
    return [_event_out(e, patient.id) for e in events]


@router.post("/events", response_model=HealthEventOut)
def create_event(
    payload: HealthEventIn,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    if payload.event_type not in EVENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"event_type must be one of {', '.join(EVENT_TYPES)}",
        )
    if not payload.title.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A title is required.")

    event = HealthEvent(
        **payload.model_dump(exclude={"title"}),
        title=payload.title.strip(),
        created_by=patient.id,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return _event_out(event, patient.id)


@router.delete("/events/{event_id}")
def delete_event(
    event_id: str,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    """Only the poster can remove their own event."""
    event = db.query(HealthEvent).filter(HealthEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    if event.created_by != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only remove events you posted.",
        )
    db.delete(event)
    db.commit()
    return {"deleted": event_id}


@router.get("/nearby-activity")
def nearby_activity(
    lat: float,
    lon: float,
    radius_km: float = 5.0,
    limit: int = 12,
    patient: Patient = Depends(get_current_patient),
):
    """
    Parks, gyms and yoga studios near the patient.

    Uses Google Places (New) when the key is configured AND the API is enabled
    on the project; otherwise returns an empty list with a reason, so the UI
    can say why rather than showing a broken panel.
    """
    settings = get_settings()
    key = settings.GOOGLE_PLACES_API_KEY
    if not key:
        return {
            "places": [],
            "available": False,
            "reason": "No Google Places API key configured (GOOGLE_PLACES_API_KEY).",
        }

    import httpx

    try:
        response = httpx.post(
            "https://places.googleapis.com/v1/places:searchNearby",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": (
                    "places.displayName,places.formattedAddress,places.location,"
                    "places.primaryTypeDisplayName,places.rating,places.googleMapsUri"
                ),
            },
            json={
                "includedTypes": FITNESS_PLACE_TYPES,
                "maxResultCount": min(limit, 20),
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lon},
                        "radius": min(radius_km, 50) * 1000,
                    }
                },
            },
            timeout=12.0,
        )
        if response.status_code != 200:
            detail = response.json().get("error", {}).get("message", response.text[:200])
            logger.warning("Places API returned %s: %s", response.status_code, detail[:200])
            return {
                "places": [],
                "available": False,
                "reason": (
                    "The Places API is not enabled for this Google Cloud project yet. "
                    "Enable 'Places API (New)' in the Google Cloud console to switch this on."
                    if "SERVICE_DISABLED" in detail or response.status_code == 403
                    else "Could not reach the Places service just now."
                ),
            }

        payload = response.json()
        places = [
            {
                "name": (p.get("displayName") or {}).get("text"),
                "address": p.get("formattedAddress"),
                "type": (p.get("primaryTypeDisplayName") or {}).get("text"),
                "rating": p.get("rating"),
                "maps_url": p.get("googleMapsUri"),
                "latitude": (p.get("location") or {}).get("latitude"),
                "longitude": (p.get("location") or {}).get("longitude"),
            }
            for p in payload.get("places", [])
        ]
        return {"places": places, "available": True, "reason": None}

    except Exception:  # noqa: BLE001
        logger.exception("Nearby activity lookup failed")
        return {"places": [], "available": False, "reason": "Could not reach the Places service."}
