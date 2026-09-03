"""
SQLAlchemy models implementing the data model from the Arogya build plan
(section 5). Kept in one file for a prototype-sized codebase; split by
domain if this grows.
"""
import enum
import secrets
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import relationship

from app.db.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


def gen_emergency_token() -> str:
    """
    Unguessable token for the public emergency-profile URL behind the QR code.
    Long and random because that URL is readable without login -- a first
    responder can't be asked to authenticate. Regenerating it instantly
    invalidates every previously printed QR code.
    """
    return secrets.token_urlsafe(32)


class Patient(Base):
    __tablename__ = "patients"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=True)
    phone = Column(String, unique=True, index=True, nullable=False)
    date_of_birth = Column(String, nullable=True)
    preferred_language = Column(String, default="en")
    created_at = Column(DateTime, default=datetime.utcnow)

    # --- Profile / emergency medical ID ---------------------------------
    # Field set follows what emergency clinicians and medical-ID guidance
    # actually ask for: blood group, allergies (especially anaphylaxis),
    # conditions, current medicines that change emergency treatment (blood
    # thinners, insulin, immunosuppressants), implanted devices, and who to
    # call. See README "Emergency profile" for sourcing.
    gender = Column(String, nullable=True)
    blood_group = Column(String, nullable=True)  # A+, O-, ...
    height_cm = Column(Float, nullable=True)
    weight_kg = Column(Float, nullable=True)
    organ_donor = Column(Boolean, default=False)
    implants_devices = Column(Text, nullable=True)  # pacemaker, ICD, stent, insulin pump
    primary_doctor_name = Column(String, nullable=True)
    primary_doctor_phone = Column(String, nullable=True)
    insurance_provider = Column(String, nullable=True)
    insurance_policy_no = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    emergency_notes = Column(Text, nullable=True)
    profile_completed = Column(Boolean, default=False)

    # Pregnancy is a time-limited state, not a chronic condition, so it lives
    # here as a flag the patient can switch off rather than in the Condition
    # table. It drives the hard red block on contraindicated medicines during
    # prescription review -- see safety_service.
    is_pregnant = Column(Boolean, default=False)
    pregnancy_due_date = Column(String, nullable=True)
    is_breastfeeding = Column(Boolean, default=False)

    emergency_token = Column(String, unique=True, index=True, default=gen_emergency_token)

    consents = relationship("ConsentRecord", back_populates="patient", cascade="all, delete-orphan")
    prescriptions = relationship("Prescription", back_populates="patient", cascade="all, delete-orphan")
    conditions = relationship("Condition", back_populates="patient", cascade="all, delete-orphan")
    allergies = relationship("Allergy", back_populates="patient", cascade="all, delete-orphan")
    health_metrics = relationship("HealthMetric", back_populates="patient", cascade="all, delete-orphan")
    surgeries = relationship("Surgery", back_populates="patient", cascade="all, delete-orphan")
    emergency_contacts = relationship(
        "EmergencyContact", back_populates="patient", cascade="all, delete-orphan"
    )
    chat_sessions = relationship("ChatSession", back_populates="patient", cascade="all, delete-orphan")


class Allergy(Base):
    """
    A known allergy. Severity matters more than the allergen alone in an
    emergency -- 'penicillin, anaphylaxis' changes treatment, 'dust, mild'
    usually doesn't -- so it's a first-class column, not free text.
    """

    __tablename__ = "allergies"

    id = Column(String, primary_key=True, default=gen_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False)
    allergen = Column(String, nullable=False)
    reaction = Column(String, nullable=True)
    severity = Column(String, default="unknown")  # mild | moderate | severe | anaphylaxis | unknown
    notes = Column(Text, nullable=True)

    patient = relationship("Patient", back_populates="allergies")


class EmergencyContact(Base):
    __tablename__ = "emergency_contacts"

    id = Column(String, primary_key=True, default=gen_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False)
    name = Column(String, nullable=False)
    relationship_to_patient = Column(String, nullable=True)  # spouse, son, neighbour...
    phone = Column(String, nullable=False)
    is_primary = Column(Boolean, default=False)

    patient = relationship("Patient", back_populates="emergency_contacts")


class ConsentRecord(Base):
    __tablename__ = "consent_records"

    id = Column(String, primary_key=True, default=gen_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False)
    consent_type = Column(String, nullable=False)  # e.g. "data_processing", "reminders", "chatbot_context"
    purpose_text = Column(Text, nullable=False)
    granted = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    withdrawn_at = Column(DateTime, nullable=True)

    patient = relationship("Patient", back_populates="consents")


class ConfirmationStatus(str, enum.Enum):
    PENDING = "pending"          # uploaded, OCR not yet run
    NEEDS_REVIEW = "needs_review"  # OCR ran, low confidence / handwriting
    CONFIRMED = "confirmed"      # patient reviewed and confirmed structured data


class Prescription(Base):
    __tablename__ = "prescriptions"

    id = Column(String, primary_key=True, default=gen_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False)
    file_path = Column(String, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    doctor_name = Column(String, nullable=True)
    ocr_raw_text = Column(Text, nullable=True)
    ocr_confidence = Column(Float, nullable=True)
    ocr_provider = Column(String, nullable=True)
    is_handwritten_guess = Column(Boolean, default=False)
    confirmation_status = Column(Enum(ConfirmationStatus), default=ConfirmationStatus.PENDING)
    confirmed_at = Column(DateTime, nullable=True)

    patient = relationship("Patient", back_populates="prescriptions")
    medications = relationship("Medication", back_populates="prescription", cascade="all, delete-orphan")


class Medication(Base):
    __tablename__ = "medications"

    id = Column(String, primary_key=True, default=gen_uuid)
    prescription_id = Column(String, ForeignKey("prescriptions.id"), nullable=False)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False)

    raw_name = Column(String, nullable=False)          # as extracted/typed
    matched_drug_id = Column(String, ForeignKey("drug_knowledge.id"), nullable=True)  # canonical match
    dosage = Column(String, nullable=True)              # e.g. "500mg"
    frequency = Column(String, nullable=True)           # e.g. "twice daily"
    duration_days = Column(Integer, nullable=True)
    route = Column(String, nullable=True)                # oral / injectable / topical
    instructions = Column(Text, nullable=True)            # "after food" etc.
    is_confirmed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    prescription = relationship("Prescription", back_populates="medications")
    matched_drug = relationship("DrugKnowledge")
    schedules = relationship("Schedule", back_populates="medication", cascade="all, delete-orphan")


class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(String, primary_key=True, default=gen_uuid)
    medication_id = Column(String, ForeignKey("medications.id"), nullable=False)
    time_of_day = Column(String, nullable=False)  # "08:00" 24h local time
    timezone = Column(String, default="Asia/Kolkata")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    medication = relationship("Medication", back_populates="schedules")
    logs = relationship("AdherenceLog", back_populates="schedule", cascade="all, delete-orphan")


class AdherenceStatus(str, enum.Enum):
    TAKEN = "taken"
    SKIPPED = "skipped"
    SNOOZED = "snoozed"
    PENDING = "pending"


class AdherenceLog(Base):
    __tablename__ = "adherence_logs"

    id = Column(String, primary_key=True, default=gen_uuid)
    schedule_id = Column(String, ForeignKey("schedules.id"), nullable=False)
    scheduled_for = Column(DateTime, nullable=False)
    status = Column(Enum(AdherenceStatus), default=AdherenceStatus.PENDING)
    recorded_at = Column(DateTime, nullable=True)

    schedule = relationship("Schedule", back_populates="logs")


class Surgery(Base):
    """
    A past operation or procedure.

    Kept separate from Condition because a surgery is a dated event that is
    over, while a condition is ongoing — and an anaesthetist or surgeon asks
    about prior operations specifically. Appears on the emergency profile:
    knowing someone has had a stent or a splenectomy changes emergency care.
    """

    __tablename__ = "surgeries"

    id = Column(String, primary_key=True, default=gen_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    year = Column(String, nullable=True)        # free text: "2021", "approx 2015"
    hospital = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="surgeries")


class HealthEvent(Base):
    """
    A community health or fitness event — a morning walk group, a free BP
    screening camp, a yoga session.

    Events are visible to every signed-in user, not just their creator: the
    point is local awareness, and an event only one person can see promotes
    nothing. `created_by` exists so a poster can remove their own event, and
    is never exposed in the API response — other users see the organiser name
    the poster typed, not the account behind it.
    """

    __tablename__ = "health_events"

    id = Column(String, primary_key=True, default=gen_uuid)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    event_type = Column(String, default="other")  # walk | yoga | screening | talk | camp | other
    starts_at = Column(DateTime, nullable=False, index=True)
    ends_at = Column(DateTime, nullable=True)

    location_name = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    organiser = Column(String, nullable=True)
    contact = Column(String, nullable=True)          # phone or URL the poster gives out
    is_free = Column(Boolean, default=True)

    created_by = Column(String, ForeignKey("patients.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_cancelled = Column(Boolean, default=False)


class HealthMetric(Base):
    """
    A single health reading: blood pressure, blood sugar, weight, or steps.

    `source` is the extension point for device sync. Everything today is
    "manual", but Health Connect (Android) or the Google Health API (Fitbit /
    Pixel Watch) would write rows here with source="health_connect" etc., and
    nothing downstream — charts, insights, the patient file — needs to change.

    Blood pressure is the reason for two value columns: it is inherently a
    pair (systolic/diastolic) and splitting it across two rows would break
    every chart and range check that treats a reading as one event.
    """

    __tablename__ = "health_metrics"

    id = Column(String, primary_key=True, default=gen_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False, index=True)

    metric_type = Column(String, nullable=False, index=True)  # blood_pressure | blood_glucose | weight | steps
    value_primary = Column(Float, nullable=False)     # systolic | mg/dL | kg | step count
    value_secondary = Column(Float, nullable=True)    # diastolic (blood pressure only)
    unit = Column(String, nullable=True)
    context = Column(String, nullable=True)           # fasting | post_meal | random | resting
    note = Column(Text, nullable=True)

    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)
    source = Column(String, default="manual")         # manual | health_connect | google_health
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="health_metrics")


class Condition(Base):
    __tablename__ = "conditions"

    id = Column(String, primary_key=True, default=gen_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False)
    name = Column(String, nullable=False)  # e.g. "diabetes_type_2" -- matches diet_guidance keys
    diagnosed_date = Column(String, nullable=True)
    notes = Column(Text, nullable=True)

    patient = relationship("Patient", back_populates="conditions")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True, default=gen_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, default=gen_uuid)
    session_id = Column(String, ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String, nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    citations = Column(Text, nullable=True)  # JSON-encoded list of source ids
    is_emergency_escalation = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("ChatSession", back_populates="messages")


class DrugKnowledge(Base):
    """
    Curated, citable drug reference data. Seeded from
    app/data/drug_knowledge.json (a small SAMPLE dataset -- replace with a
    licensed drug database such as a CIMS/MIMS-equivalent provider, or
    RxNorm/openFDA for structured composition/class data, before any
    production/clinical use).
    """

    __tablename__ = "drug_knowledge"

    id = Column(String, primary_key=True, default=gen_uuid)
    generic_name = Column(String, nullable=False, index=True)
    brand_names = Column(Text, nullable=True)  # JSON-encoded list
    composition = Column(String, nullable=False)
    strength = Column(String, nullable=True)
    drug_class = Column(String, nullable=True)
    route = Column(String, nullable=True)
    storage_instructions = Column(Text, nullable=True)
    common_interactions = Column(Text, nullable=True)  # JSON-encoded list
    contraindications = Column(Text, nullable=True)     # JSON-encoded list
    conditions_treated = Column(Text, nullable=True)    # JSON-encoded list, matches Condition.name
    source_citation = Column(String, nullable=True)

    price_entries = relationship("PriceEntry", back_populates="drug", cascade="all, delete-orphan")
    products = relationship("MedicineProduct", back_populates="drug")


class PriceEntry(Base):
    __tablename__ = "price_entries"

    id = Column(String, primary_key=True, default=gen_uuid)
    drug_id = Column(String, ForeignKey("drug_knowledge.id"), nullable=False)
    product_name = Column(String, nullable=False)
    manufacturer = Column(String, nullable=True)
    is_generic = Column(Boolean, default=False)
    price_inr = Column(Float, nullable=False)
    unit = Column(String, default="per strip of 10 tablets")
    source = Column(String, nullable=True)
    last_updated = Column(String, nullable=True)

    drug = relationship("DrugKnowledge", back_populates="price_entries")


class MedicineProduct(Base):
    """
    Bulk catalogue of Indian branded medicines, imported from the open
    Indian-Medicine-Dataset (MIT licensed, ~254k products). This is the wide,
    shallow half of the drug data: it knows what a brand name is made of and
    roughly what it costs, but carries no clinical safety fields.

    It deliberately sits alongside DrugKnowledge rather than replacing it.
    DrugKnowledge stays the narrow, deep, hand-curated set that safety
    screening reads (contraindications, interactions, pregnancy). When an
    imported product's composition matches a curated drug, drug_id links the
    two so that scanning any of thousands of brand names still runs the full
    safety check; when it doesn't, the product is still searchable and
    priceable, just without clinical flags -- which the UI must say plainly
    rather than implying the medicine was cleared.
    """

    __tablename__ = "medicine_products"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False, index=True)
    name_key = Column(String, nullable=False, index=True)   # lowercased, for exact/prefix lookup
    manufacturer = Column(String, nullable=True)
    price_inr = Column(Float, nullable=True)
    pack_size_label = Column(String, nullable=True)
    composition = Column(String, nullable=True)             # human-readable, with strengths
    composition_key = Column(String, nullable=True, index=True)  # normalised "a+b", no strengths
    strength_key = Column(String, nullable=True)                 # "500mg+125mg", in ingredient order
    dose_form = Column(String, nullable=True)                    # tablet / capsule / syrup / injection...
    # Comparing a strip of 10 against a strip of 15 by pack price makes the
    # bigger pack look dearer when it is actually cheaper per dose, so the
    # per-unit figure is what price comparison sorts on.
    pack_count = Column(Integer, nullable=True)
    price_per_unit = Column(Float, nullable=True)
    # composition + strength + form. Two products only belong in the same
    # price comparison if all three match -- 650mg paracetamol tablets are not
    # interchangeable with a 500mg syrup, and quoting a saving across that gap
    # is telling the patient something untrue.
    formulation_key = Column(String, nullable=True, index=True)
    is_discontinued = Column(Boolean, default=False)
    is_generic = Column(Boolean, default=False)
    # NULL means unknown, not "over the counter" -- only the 1mg import
    # carries this fact, so products known solely from the other source have
    # no answer and the UI must not imply one.
    prescription_required = Column(Boolean, nullable=True)
    drug_id = Column(String, ForeignKey("drug_knowledge.id"), nullable=True, index=True)
    source = Column(String, nullable=True)

    drug = relationship("DrugKnowledge", back_populates="products")


class Pharmacy(Base):
    __tablename__ = "pharmacies"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    address = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    phone = Column(String, nullable=True)
    source = Column(String, default="mock")


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=True)
    phone = Column(String, unique=True, index=True, nullable=False)
    specialization = Column(String, nullable=True)
    license_no = Column(String, nullable=True)
    clinic_name = Column(String, nullable=True)
    clinic_address = Column(Text, nullable=True)
    consultation_fee_inr = Column(Float, nullable=True)
    languages = Column(String, nullable=True)          # comma-separated
    # A doctor with no name or specialisation is useless in the patient's
    # picker, so an incomplete profile is hidden from it rather than shown as
    # "null". Set once the doctor fills in their details.
    profile_completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    appointments = relationship("Appointment", back_populates="doctor", cascade="all, delete-orphan")
    availability = relationship(
        "DoctorAvailability", back_populates="doctor", cascade="all, delete-orphan"
    )
    time_off = relationship("DoctorTimeOff", back_populates="doctor", cascade="all, delete-orphan")


class DoctorAvailability(Base):
    """
    A doctor's recurring clinic hours for one weekday.

    Slots used to be a hardcoded list, identical for every doctor and every
    date -- so a patient could book Sunday 4:30pm with a doctor who only sits
    Monday mornings, and the doctor had no way to say otherwise. Availability
    is per doctor, per weekday, and generates the bookable slots.

    A weekday can hold more than one row, which is how an Indian OPD actually
    runs: a morning session and an evening session with a long gap between.
    """

    __tablename__ = "doctor_availability"

    id = Column(String, primary_key=True, default=gen_uuid)
    doctor_id = Column(String, ForeignKey("doctors.id"), nullable=False, index=True)
    weekday = Column(Integer, nullable=False)          # 0 = Monday ... 6 = Sunday
    start_time = Column(String, nullable=False)        # "09:00", 24-hour
    end_time = Column(String, nullable=False)          # "13:00"
    slot_minutes = Column(Integer, default=30)
    active = Column(Boolean, default=True)

    doctor = relationship("Doctor", back_populates="availability")


class DoctorTimeOff(Base):
    """A single date the doctor is not seeing patients, whatever the weekday
    schedule says -- leave, a conference, a public holiday."""

    __tablename__ = "doctor_time_off"

    id = Column(String, primary_key=True, default=gen_uuid)
    doctor_id = Column(String, ForeignKey("doctors.id"), nullable=False, index=True)
    date = Column(String, nullable=False, index=True)  # YYYY-MM-DD
    reason = Column(String, nullable=True)

    doctor = relationship("Doctor", back_populates="time_off")


class PatientRecordEdit(Base):
    """
    Audit trail for changes a doctor makes to a patient's record.

    A clinician correcting a record is normal and necessary -- patients
    mistype their blood group, forget a surgery, or record an allergy as
    "mild" that put them in hospital. But an edit with no trace of who made it
    is not a medical record, it is a rumour: the patient cannot tell what they
    entered from what a doctor changed, and neither can the next clinician.

    Every field a doctor touches is written here with the old and new value.
    Nothing in the app deletes from this table.
    """

    __tablename__ = "patient_record_edits"

    id = Column(String, primary_key=True, default=gen_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = Column(String, ForeignKey("doctors.id"), nullable=False, index=True)
    field = Column(String, nullable=False)          # "blood_group", "allergy.added", ...
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)            # why the doctor changed it
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    patient = relationship("Patient", backref="record_edits")
    doctor = relationship("Doctor")


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(String, primary_key=True, default=gen_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = Column(String, ForeignKey("doctors.id"), nullable=False, index=True)
    date = Column(String, nullable=False, index=True)  # YYYY-MM-DD
    time_slot = Column(String, nullable=False)         # "09:30", 24-hour
    status = Column(String, default="pending")  # pending | confirmed | cancelled | completed
    notes = Column(Text, nullable=True)                # why the patient is coming
    doctor_notes = Column(Text, nullable=True)         # what the doctor recorded after
    # Who put it in the diary. A doctor scheduling a follow-up and a patient
    # requesting a slot are different acts: the first is already agreed, so it
    # starts confirmed rather than pending.
    created_by = Column(String, default="patient")     # patient | doctor
    cancelled_by = Column(String, nullable=True)       # patient | doctor
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    patient = relationship("Patient", backref="appointments")
    doctor = relationship("Doctor", back_populates="appointments")

    __table_args__ = (
        # Two patients cannot hold the same slot. The router checks first for a
        # friendly error, but the check-then-insert is a race: two requests can
        # both pass it. Only the database can actually settle that.
        #
        # Partial index so cancelled appointments do not block the slot from
        # being rebooked.
        Index(
            "ux_appointment_slot_active",
            "doctor_id",
            "date",
            "time_slot",
            unique=True,
            sqlite_where=text("status IN ('pending','confirmed')"),
        ),
    )
