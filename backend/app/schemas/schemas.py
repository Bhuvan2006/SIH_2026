"""Pydantic request/response schemas, grouped by domain."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------- Auth ----------

class OTPRequest(BaseModel):
    phone: str


class OTPRequestResponse(BaseModel):
    message: str
    dev_otp: Optional[str] = None  # only populated in OTP_DEV_MODE, for testability


class OTPVerify(BaseModel):
    phone: str
    otp: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    patient_id: Optional[str] = None
    doctor_id: Optional[str] = None
    is_new_patient: bool = False
    is_new_doctor: bool = False
    role: str = "patient"


# ---------- Patient ----------

class PatientUpdate(BaseModel):
    name: Optional[str] = None
    date_of_birth: Optional[str] = None
    preferred_language: Optional[str] = None
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    organ_donor: Optional[bool] = None
    implants_devices: Optional[str] = None
    primary_doctor_name: Optional[str] = None
    primary_doctor_phone: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_policy_no: Optional[str] = None
    address: Optional[str] = None
    emergency_notes: Optional[str] = None
    profile_completed: Optional[bool] = None
    is_pregnant: Optional[bool] = None
    pregnancy_due_date: Optional[str] = None
    is_breastfeeding: Optional[bool] = None


class SurgeryIn(BaseModel):
    name: str
    year: Optional[str] = None
    hospital: Optional[str] = None
    notes: Optional[str] = None


class SurgeryOut(SurgeryIn):
    id: str

    class Config:
        from_attributes = True


class PatientOut(BaseModel):
    id: str
    name: Optional[str]
    phone: str
    date_of_birth: Optional[str]
    preferred_language: str
    created_at: datetime
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    organ_donor: Optional[bool] = None
    implants_devices: Optional[str] = None
    primary_doctor_name: Optional[str] = None
    primary_doctor_phone: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_policy_no: Optional[str] = None
    address: Optional[str] = None
    emergency_notes: Optional[str] = None
    profile_completed: bool = False
    is_pregnant: bool = False
    pregnancy_due_date: Optional[str] = None
    is_breastfeeding: bool = False

    class Config:
        from_attributes = True


# ---------- Allergies / emergency contacts ----------

class AllergyIn(BaseModel):
    allergen: str
    reaction: Optional[str] = None
    severity: str = "unknown"  # mild | moderate | severe | anaphylaxis | unknown
    notes: Optional[str] = None


class AllergyOut(AllergyIn):
    id: str

    class Config:
        from_attributes = True


class EmergencyContactIn(BaseModel):
    name: str
    relationship_to_patient: Optional[str] = None
    phone: str
    is_primary: bool = False


class EmergencyContactOut(EmergencyContactIn):
    id: str

    class Config:
        from_attributes = True


class ConsentIn(BaseModel):
    consent_type: str
    purpose_text: str
    granted: bool = True


class ConsentOut(BaseModel):
    id: str
    consent_type: str
    purpose_text: str
    granted: bool
    created_at: datetime
    withdrawn_at: Optional[datetime]

    class Config:
        from_attributes = True


# ---------- Community health events ----------

class HealthEventIn(BaseModel):
    title: str
    description: Optional[str] = None
    event_type: str = "other"  # walk | yoga | screening | talk | camp | other
    starts_at: datetime
    ends_at: Optional[datetime] = None
    location_name: Optional[str] = None
    address: Optional[str] = None
    organiser: Optional[str] = None
    contact: Optional[str] = None
    is_free: bool = True


class HealthEventOut(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    event_type: str
    starts_at: datetime
    ends_at: Optional[datetime] = None
    location_name: Optional[str] = None
    address: Optional[str] = None
    organiser: Optional[str] = None
    contact: Optional[str] = None
    is_free: bool
    is_cancelled: bool = False
    # Whether the signed-in user posted this, so the UI can offer Remove
    # without ever revealing who posted anything else.
    is_mine: bool = False

    class Config:
        from_attributes = True


# ---------- Health metrics ----------

class HealthMetricIn(BaseModel):
    metric_type: str  # blood_pressure | blood_glucose | weight | steps
    value_primary: float
    value_secondary: Optional[float] = None  # diastolic, for blood pressure
    unit: Optional[str] = None
    context: Optional[str] = None  # fasting | post_meal | random | resting
    note: Optional[str] = None
    recorded_at: Optional[datetime] = None


class HealthMetricOut(BaseModel):
    id: str
    metric_type: str
    value_primary: float
    value_secondary: Optional[float] = None
    unit: Optional[str] = None
    context: Optional[str] = None
    note: Optional[str] = None
    recorded_at: datetime
    source: str = "manual"
    band_label: Optional[str] = None
    band_tone: Optional[str] = None

    class Config:
        from_attributes = True


class ConditionIn(BaseModel):
    name: str
    diagnosed_date: Optional[str] = None
    notes: Optional[str] = None


class ConditionOut(ConditionIn):
    id: str

    class Config:
        from_attributes = True


# ---------- Prescriptions / OCR ----------

class SafetyFlagOut(BaseModel):
    kind: str          # banned | allergy | contraindication | duplicate | interaction
    severity: str      # critical | warning | info
    title: str
    detail: str
    action: str
    source: Optional[str] = None


class ExtractedMedication(BaseModel):
    raw_name: str
    matched_drug_id: Optional[str] = None
    matched_generic_name: Optional[str] = None
    match_score: Optional[float] = None
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    duration_days: Optional[int] = None
    instructions: Optional[str] = None
    # Inline price comparison + safety screening, so the review screen can
    # show both without a second round-trip per medicine.
    price_options: list["PriceOption"] = Field(default_factory=list)
    cheapest: Optional["PriceOption"] = None
    safety_flags: list[SafetyFlagOut] = Field(default_factory=list)
    # False means this medicine was recognised from the bulk brand catalogue,
    # which has no contraindication, interaction or pregnancy data. An empty
    # safety_flags list then means "not checked", NOT "checked and clear", and
    # the UI must say which.
    has_safety_data: bool = True


class MedicineScreenItem(BaseModel):
    """One row from the review table, as the patient currently has it."""

    raw_name: str
    matched_drug_id: Optional[str] = None
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    duration_days: Optional[int] = None
    instructions: Optional[str] = None


class MedicineScreenRequest(BaseModel):
    medications: list[MedicineScreenItem] = Field(default_factory=list)


class MedicineScreenResponse(BaseModel):
    medications: list["ExtractedMedication"] = Field(default_factory=list)
    # True when any medicine carries a critical flag, so the UI can require an
    # explicit acknowledgement before the prescription is saved.
    has_critical: bool = False


class PrescriptionUploadResponse(BaseModel):
    prescription_id: str
    ocr_confidence: float
    is_handwritten_guess: bool
    confirmation_status: str
    ocr_raw_text: str
    extracted_medications: list[ExtractedMedication]
    review_message: str
    # Warnings that apply to the prescription as a whole rather than to one
    # matched medicine -- e.g. a banned drug spotted in the raw text that our
    # knowledge base doesn't stock, so it never became an extracted medicine.
    prescription_flags: list[SafetyFlagOut] = Field(default_factory=list)


class MedicationConfirm(BaseModel):
    raw_name: str
    matched_drug_id: Optional[str] = None
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    duration_days: Optional[int] = None
    route: Optional[str] = None
    instructions: Optional[str] = None
    reminder_times: list[str] = Field(default_factory=list)  # ["08:00", "20:00"]


class PrescriptionConfirmRequest(BaseModel):
    doctor_name: Optional[str] = None
    medications: list[MedicationConfirm]


class MedicationOut(BaseModel):
    id: str
    raw_name: str
    matched_drug_id: Optional[str]
    dosage: Optional[str]
    frequency: Optional[str]
    duration_days: Optional[int]
    route: Optional[str]
    instructions: Optional[str]
    is_confirmed: bool
    # Enriched for display: the canonical drug name, when reminders fire, and
    # any storage requirement -- so "My medications" can show the full picture
    # instead of four sparse columns.
    matched_generic_name: Optional[str] = None
    reminder_times: list[str] = Field(default_factory=list)
    storage_note: Optional[str] = None
    drug_class: Optional[str] = None

    class Config:
        from_attributes = True


class PrescriptionOut(BaseModel):
    id: str
    uploaded_at: datetime
    doctor_name: Optional[str]
    confirmation_status: str
    ocr_confidence: Optional[float]
    is_handwritten_guess: bool
    medications: list[MedicationOut]

    class Config:
        from_attributes = True


# ---------- Schedules / adherence ----------

class ScheduleOut(BaseModel):
    id: str
    medication_id: str
    time_of_day: str
    timezone: str
    active: bool

    class Config:
        from_attributes = True


class AdherenceUpdate(BaseModel):
    status: str  # taken | skipped | snoozed


class UpcomingReminder(BaseModel):
    schedule_id: str
    medication_id: str
    drug_name: str
    time_of_day: str
    dosage: Optional[str]
    instructions: Optional[str]
    storage_note: Optional[str]
    adherence_log_id: Optional[str] = None
    status: str = "pending"


# ---------- Chatbot ----------

class ChatAskRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    language: Optional[str] = None  # defaults to patient's preferred_language


class ChatCitation(BaseModel):
    source_id: str
    label: str


class ChatAskResponse(BaseModel):
    session_id: str
    answer: str
    citations: list[ChatCitation]
    is_emergency_escalation: bool
    disclaimer: str


# ---------- Price comparison ----------

class PriceOption(BaseModel):
    product_name: str
    manufacturer: Optional[str]
    is_generic: bool
    price_inr: float
    unit: str
    savings_pct_vs_costliest: Optional[float] = None
    # None means unknown, not over-the-counter. Only products imported from
    # the 1mg dataset carry this fact.
    prescription_required: Optional[bool] = None


class PriceComparisonResponse(BaseModel):
    drug_id: str
    generic_name: str
    composition: str
    options: list[PriceOption]
    cheapest: Optional[PriceOption]
    disclaimer: str


# ---------- Pharmacy locator ----------

class PharmacyOut(BaseModel):
    id: str
    name: str
    address: str
    latitude: float
    longitude: float
    phone: Optional[str]
    distance_km: Optional[float] = None

    class Config:
        from_attributes = True


# ExtractedMedication forward-references PriceOption, which is declared further
# down this module. Resolve it now that both names exist.
ExtractedMedication.model_rebuild()
PrescriptionUploadResponse.model_rebuild()


# ---------- Doctor ----------

class DoctorOut(BaseModel):
    id: str
    name: Optional[str] = None
    phone: str
    specialization: Optional[str] = None
    license_no: Optional[str] = None
    clinic_name: Optional[str] = None
    clinic_address: Optional[str] = None
    consultation_fee_inr: Optional[float] = None
    languages: Optional[str] = None
    profile_completed: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class DoctorUpdate(BaseModel):
    name: Optional[str] = None
    specialization: Optional[str] = None
    license_no: Optional[str] = None
    clinic_name: Optional[str] = None
    clinic_address: Optional[str] = None
    consultation_fee_inr: Optional[float] = None
    languages: Optional[str] = None


# ---------- Doctor-side record editing ----------

class DoctorPatientUpdate(BaseModel):
    """
    Clinical fields a doctor may correct on a patient's record.

    Deliberately NOT the whole patient: a doctor has no business changing the
    phone number the account signs in with, the preferred language, or the
    insurance details. This is the clinical picture, not the account.
    """

    blood_group: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    implants_devices: Optional[str] = None
    emergency_notes: Optional[str] = None
    is_pregnant: Optional[bool] = None
    pregnancy_due_date: Optional[str] = None
    is_breastfeeding: Optional[bool] = None
    # Recorded against every field changed, so the audit trail says why.
    reason: Optional[str] = None


class RecordEditOut(BaseModel):
    id: str
    field: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    reason: Optional[str] = None
    created_at: datetime
    doctor_name: Optional[str] = None

    class Config:
        from_attributes = True


# ---------- Patient summary ----------

class SummaryFactOut(BaseModel):
    label: str
    detail: str
    tone: str = "neutral"


class PatientSummaryOut(BaseModel):
    patient_id: str
    patient_name: Optional[str] = None
    age_years: Optional[int] = None
    narrative: str
    # "model" or "deterministic" -- the UI says which, so a doctor knows
    # whether a language model wrote the prose.
    narrative_source: str
    highlights: list[SummaryFactOut] = Field(default_factory=list)
    medicines: list[dict] = Field(default_factory=list)
    safety_flags: list[dict] = Field(default_factory=list)
    vitals: list[dict] = Field(default_factory=list)
    adherence: Optional[dict] = None
    last_seen: Optional[str] = None
    generated_at: str


# ---------- Availability ----------

class AvailabilityIn(BaseModel):
    weekday: int = Field(ge=0, le=6)      # 0 = Monday
    start_time: str                        # "09:00", 24-hour
    end_time: str                          # "13:00"
    slot_minutes: int = Field(default=30, ge=5, le=180)
    active: bool = True


class AvailabilityOut(AvailabilityIn):
    id: str
    doctor_id: str

    class Config:
        from_attributes = True


class TimeOffIn(BaseModel):
    date: str                              # YYYY-MM-DD
    reason: Optional[str] = None


class TimeOffOut(TimeOffIn):
    id: str
    doctor_id: str

    class Config:
        from_attributes = True


class SlotOut(BaseModel):
    time_slot: str
    available: bool
    reason: Optional[str] = None


class DaySlotsOut(BaseModel):
    date: str
    slots: list[SlotOut] = Field(default_factory=list)
    # Set when the day yields nothing, so the UI can explain why instead of
    # showing a bare "no slots".
    closed_reason: Optional[str] = None


# ---------- Appointments ----------

class AppointmentIn(BaseModel):
    doctor_id: str
    date: str
    time_slot: str
    notes: Optional[str] = None


class DoctorAppointmentIn(BaseModel):
    """A doctor putting an appointment in their own diary for a patient."""

    patient_id: str
    date: str
    time_slot: str
    notes: Optional[str] = None


class AppointmentOut(BaseModel):
    id: str
    patient_id: str
    doctor_id: str
    date: str
    time_slot: str
    time_slot_label: Optional[str] = None   # "2:30 PM", for display
    status: str
    notes: Optional[str] = None
    doctor_notes: Optional[str] = None
    created_by: Optional[str] = None
    cancelled_by: Optional[str] = None
    is_past: bool = False
    created_at: datetime

    # Expanded on endpoints where the counterparty matters.
    doctor: Optional[DoctorOut] = None
    patient: Optional[PatientOut] = None

    class Config:
        from_attributes = True


class AppointmentUpdate(BaseModel):
    status: Optional[str] = None       # confirmed | cancelled | completed
    doctor_notes: Optional[str] = None

