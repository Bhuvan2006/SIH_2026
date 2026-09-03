"""
End-to-end smoke tests over the FastAPI app using an isolated in-memory
SQLite DB (separate from the dev arogya.db file). Run with: pytest -v
"""
import io
import json
import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import StaticPool

from app.db import database
from app.db.seed import seed_if_empty
from app.main import app

# Rebind the app's DB engine to a shared in-memory SQLite instance so all
# connections in this test process see the same schema/data.
test_engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestSessionLocal = scoped_session(sessionmaker(bind=test_engine, autoflush=False, autocommit=False))
database.Base.metadata.create_all(bind=test_engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[database.get_db] = override_get_db

client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def _seed_once():
    db = TestSessionLocal()
    seed_if_empty(db)
    db.close()


def _make_prescription_image() -> bytes:
    img = Image.new("RGB", (800, 200), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
    except Exception:
        font = ImageFont.load_default()
    d.text((20, 20), "1. Metformin 500mg BD x 30 days", fill="black", font=font)
    d.text((20, 70), "2. Paracetamol 650mg SOS for fever", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _login(phone="+911234500000"):
    r = client.post("/auth/otp/request", json={"phone": phone})
    assert r.status_code == 200
    r = client.post("/auth/otp/verify", json={"phone": phone, "otp": "000000"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_health():
    assert client.get("/health").status_code == 200


def test_auth_flow():
    headers = _login()
    r = client.get("/patients/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["phone"] == "+911234500000"


def test_prescription_upload_and_confirm_flow():
    headers = _login("+911234500001")
    img_bytes = _make_prescription_image()

    r = client.post(
        "/prescriptions/upload",
        headers=headers,
        files={"file": ("rx.png", img_bytes, "image/png")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["confirmation_status"] == "needs_review"
    names = {m["matched_generic_name"] for m in body["extracted_medications"]}
    assert "Metformin" in names
    assert "Paracetamol" in names

    prescription_id = body["prescription_id"]
    confirm_payload = {
        "doctor_name": "Dr. Test",
        "medications": [
            {
                "raw_name": "Metformin",
                "matched_drug_id": body["extracted_medications"][0]["matched_drug_id"],
                "dosage": "500mg",
                "frequency": "twice daily",
                "duration_days": 30,
                "reminder_times": ["08:00", "20:00"],
            }
        ],
    }
    r = client.post(f"/prescriptions/{prescription_id}/confirm", headers=headers, json=confirm_payload)
    assert r.status_code == 200
    assert r.json()["confirmation_status"] == "confirmed"

    # Reminders should now exist
    r = client.get("/reminders/upcoming", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 2

    # Confirming a prescription refreshes the patient's data file, which is
    # what the chatbot reads to answer questions about their own medicines.
    from app.services.patient_file_service import patient_file_path

    me = client.get("/patients/me", headers=headers).json()
    record_path = patient_file_path(me["id"])
    assert record_path.exists()
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert any(m["matched_generic_name"] == "Metformin" for m in record["current_medications"])


def test_prescription_upload_rejects_bad_content_type():
    headers = _login("+911234500002")
    r = client.post(
        "/prescriptions/upload",
        headers=headers,
        files={"file": ("rx.txt", b"not an image", "text/plain")},
    )
    assert r.status_code == 400


def test_chatbot_grounded_answer_and_citations():
    headers = _login("+911234500003")
    r = client.post("/chat/ask", headers=headers, json={"message": "How should I store insulin?"})
    assert r.status_code == 200
    body = r.json()
    assert body["is_emergency_escalation"] is False
    assert len(body["citations"]) > 0
    assert "2" in body["answer"] or "insulin" in body["answer"].lower()


def test_chatbot_emergency_escalation():
    headers = _login("+911234500004")
    r = client.post("/chat/ask", headers=headers, json={"message": "I have severe chest pain"})
    assert r.status_code == 200
    body = r.json()
    assert body["is_emergency_escalation"] is True
    assert body["citations"] == []


def test_chatbot_unknown_topic_does_not_hallucinate():
    headers = _login("+911234500005")
    r = client.post("/chat/ask", headers=headers, json={"message": "What's the weather like today?"})
    assert r.status_code == 200
    body = r.json()
    assert body["citations"] == []


def test_price_comparison_shows_cheaper_generic():
    headers = _login("+911234500006")
    r = client.get("/prices/search", headers=headers, params={"q": "Paracetamol"})
    assert r.status_code == 200
    drug_id = r.json()[0]["drug_id"]

    r = client.get(f"/prices/by-drug/{drug_id}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["cheapest"]["is_generic"] is True
    assert body["cheapest"]["price_inr"] < max(o["price_inr"] for o in body["options"])


def test_pharmacy_locator_returns_sorted_by_distance():
    headers = _login("+911234500007")
    r = client.get("/pharmacies/nearby", headers=headers, params={"lat": 12.9352, "lon": 77.6245, "radius_km": 50})
    assert r.status_code == 200
    results = r.json()
    assert len(results) > 0
    distances = [p["distance_km"] for p in results]
    assert distances == sorted(distances)


def test_consent_grant_and_withdraw():
    headers = _login("+911234500008")
    r = client.post(
        "/patients/me/consent",
        headers=headers,
        json={"consent_type": "data_processing", "purpose_text": "Store my prescriptions", "granted": True},
    )
    assert r.status_code == 200
    consent_id = r.json()["id"]

    r = client.delete(f"/patients/me/consent/{consent_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["granted"] is False
    assert r.json()["withdrawn_at"] is not None


def test_unauthenticated_request_rejected():
    r = client.get("/patients/me")
    assert r.status_code == 401
