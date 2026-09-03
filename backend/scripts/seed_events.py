"""
Seeds a few sample community health events so the Health hub noticeboard
isn't empty on a fresh install.

    python scripts/seed_events.py [--clear]

These are illustrative placeholders, not real events — the venues are real
Bengaluru landmarks but no one has organised these. Replace or clear them
before real users see the noticeboard, or they'll turn up to nothing.

Safe to re-run: it skips events whose title already exists.
"""
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import SessionLocal  # noqa: E402
from app.models.models import HealthEvent  # noqa: E402


def _at(days_ahead: int, hour: int, minute: int = 0) -> datetime:
    d = datetime.now() + timedelta(days=days_ahead)
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0)


SAMPLES = [
    {
        "title": "Sunday morning walking group",
        "description": (
            "An easy-paced 45-minute walk around the lake, open to all ages and fitness levels. "
            "Bring water. We meet near the main gate and finish with tea."
        ),
        "event_type": "walk",
        "starts_at": _at(3, 6, 30),
        "ends_at": _at(3, 7, 30),
        "location_name": "Lalbagh Botanical Garden",
        "address": "Mavalli, Bengaluru 560004",
        "organiser": "Basavanagudi Walkers Club",
        "contact": "+91 98450 11223",
        "is_free": True,
    },
    {
        "title": "Free blood pressure & sugar screening camp",
        "description": (
            "Walk-in screening for blood pressure and random blood sugar, run by volunteer "
            "nurses. Results given on the spot with advice on whether to see a doctor. "
            "No appointment needed — bring any medicines you currently take."
        ),
        "event_type": "screening",
        "starts_at": _at(6, 9, 0),
        "ends_at": _at(6, 13, 0),
        "location_name": "Ward 142 Community Hall",
        "address": "5th Block, Jayanagar, Bengaluru 560041",
        "organiser": "Jayanagar Residents' Welfare Association",
        "contact": "+91 80 2663 4400",
        "is_free": True,
    },
    {
        "title": "Yoga for blood pressure and stress",
        "description": (
            "Beginner-friendly session focused on breathing and gentle stretches that help with "
            "blood pressure and sleep. Mats provided. Please avoid a heavy meal beforehand."
        ),
        "event_type": "yoga",
        "starts_at": _at(9, 17, 30),
        "ends_at": _at(9, 18, 30),
        "location_name": "Cubbon Park (bandstand lawn)",
        "address": "Kasturba Road, Bengaluru 560001",
        "organiser": "City Wellness Collective",
        "contact": "wellnesscollective.example.in",
        "is_free": True,
    },
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clear", action="store_true", help="remove seeded sample events first")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        titles = [s["title"] for s in SAMPLES]

        if args.clear:
            removed = (
                db.query(HealthEvent)
                .filter(HealthEvent.title.in_(titles))
                .delete(synchronize_session=False)
            )
            db.commit()
            print(f"removed {removed} sample event(s)")
            return

        existing = {
            t for (t,) in db.query(HealthEvent.title).filter(HealthEvent.title.in_(titles)).all()
        }
        added = 0
        for sample in SAMPLES:
            if sample["title"] in existing:
                continue
            # created_by stays NULL: these are seeded, so no patient owns them
            # and no one gets a Remove button for someone else's event.
            db.add(HealthEvent(**sample))
            added += 1

        db.commit()
        print(f"added {added} sample event(s); {len(existing)} already present")
    finally:
        db.close()


if __name__ == "__main__":
    main()
