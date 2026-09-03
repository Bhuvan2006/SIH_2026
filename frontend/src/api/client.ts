import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: API_BASE_URL,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("arogya_token");
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// If the token is invalid/expired, bounce back to login rather than
// showing a confusing broken screen.
api.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("arogya_token");
      localStorage.removeItem("arogya_patient_id");
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

// ---------- Types ----------

export interface Patient {
  id: string;
  name: string | null;
  phone: string;
  date_of_birth: string | null;
  preferred_language: string;
  created_at: string;
  gender?: string | null;
  blood_group?: string | null;
  height_cm?: number | null;
  weight_kg?: number | null;
  organ_donor?: boolean | null;
  implants_devices?: string | null;
  primary_doctor_name?: string | null;
  primary_doctor_phone?: string | null;
  insurance_provider?: string | null;
  insurance_policy_no?: string | null;
  address?: string | null;
  emergency_notes?: string | null;
  profile_completed?: boolean;
  is_pregnant?: boolean;
  pregnancy_due_date?: string | null;
  is_breastfeeding?: boolean;
}

export interface Allergy {
  id: string;
  allergen: string;
  reaction: string | null;
  severity: string;
  notes: string | null;
}

export interface Surgery {
  id: string;
  name: string;
  year: string | null;
  hospital: string | null;
  notes: string | null;
}

export interface EmergencyContact {
  id: string;
  name: string;
  relationship_to_patient: string | null;
  phone: string;
  is_primary: boolean;
}

export interface EmergencyProfile {
  name: string | null;
  phone: string;
  date_of_birth: string | null;
  gender: string | null;
  blood_group: string | null;
  height_cm: number | null;
  weight_kg: number | null;
  organ_donor: boolean;
  implants_devices: string | null;
  emergency_notes: string | null;
  address: string | null;
  primary_doctor: { name: string | null; phone: string | null };
  insurance: { provider: string | null; policy_no: string | null };
  critical_alerts: string[];
  allergies: { allergen: string; reaction: string | null; severity: string }[];
  conditions: { name: string; notes: string | null }[];
  emergency_contacts: {
    name: string;
    relationship: string | null;
    phone: string;
    is_primary: boolean;
  }[];
  medications: { name: string; dosage: string | null; frequency: string | null }[];
}

export interface DashboardInsights {
  has_enough_data: boolean;
  days_tracked: number;
  adherence: {
    percent: number;
    target_percent: number;
    doses_taken: number;
    doses_expected: number;
    days_covered: number;
    days_total: number;
    daily_series: { date: string; expected: number; taken: number }[];
  };
  per_medicine: {
    medication_id: string;
    name: string;
    taken: number;
    missed: number;
    total: number;
    percent: number;
  }[];
  worst_slot: { time_of_day: string; missed: number; total: number } | null;
  streak: { current: number; best: number };
  refills: {
    medication_id: string;
    name: string;
    days_left: number;
    runs_out_on: string;
    duration_days: number;
  }[];
  savings: {
    total_per_pack: number;
    items: {
      medication_id: string;
      name: string;
      current_product: string;
      current_price: number;
      cheapest_product: string;
      cheapest_price: number;
      saving_per_pack: number;
      unit: string;
    }[];
  };
}

export interface DueReminder {
  schedule_id: string;
  adherence_log_id: string;
  drug_name: string;
  dosage: string | null;
  instructions: string | null;
  time_of_day: string;
  scheduled_for: string;
  minutes_late: number;
}

export const BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"] as const;
export const ALLERGY_SEVERITIES = [
  "unknown",
  "mild",
  "moderate",
  "severe",
  "anaphylaxis",
] as const;

export interface SafetyFlag {
  kind:
    | "banned"
    | "allergy"
    | "pregnancy"
    | "contraindication"
    | "duplicate"
    | "interaction"
    | "menopause";
  severity: "critical" | "warning" | "info";
  title: string;
  detail: string;
  action: string;
  source: string | null;
}

export interface ExtractedMedication {
  raw_name: string;
  matched_drug_id: string | null;
  matched_generic_name: string | null;
  match_score: number | null;
  dosage: string | null;
  frequency: string | null;
  duration_days: number | null;
  instructions: string | null;
  price_options?: PriceOption[];
  cheapest?: PriceOption | null;
  safety_flags?: SafetyFlag[];
  /**
   * False when the medicine was recognised from the bulk brand catalogue,
   * which carries no contraindication, interaction or pregnancy data. An
   * empty safety_flags list then means "not checked", NOT "checked and
   * clear" -- the UI must not show a reassuring badge in that case.
   */
  has_safety_data?: boolean;
}

export interface PrescriptionUploadResponse {
  prescription_id: string;
  ocr_confidence: number;
  is_handwritten_guess: boolean;
  confirmation_status: string;
  ocr_raw_text: string;
  extracted_medications: ExtractedMedication[];
  review_message: string;
  prescription_flags?: SafetyFlag[];
}

export interface UpcomingReminder {
  schedule_id: string;
  medication_id: string;
  drug_name: string;
  time_of_day: string;
  dosage: string | null;
  instructions: string | null;
  storage_note: string | null;
  adherence_log_id: string | null;
  status: string;
}

export interface ChatCitation {
  source_id: string;
  label: string;
}

export interface ChatAskResponse {
  session_id: string;
  answer: string;
  citations: ChatCitation[];
  is_emergency_escalation: boolean;
  disclaimer: string;
}

export interface PriceOption {
  product_name: string;
  manufacturer: string | null;
  is_generic: boolean;
  price_inr: number;
  unit: string;
  savings_pct_vs_costliest: number | null;
  /** null = unknown, NOT over-the-counter. Only 1mg-sourced rows know this. */
  prescription_required?: boolean | null;
}

export interface PriceComparisonResponse {
  drug_id: string;
  generic_name: string;
  composition: string;
  options: PriceOption[];
  cheapest: PriceOption | null;
  disclaimer: string;
}

export interface Pharmacy {
  id: string;
  name: string;
  address: string;
  latitude: number;
  longitude: number;
  phone: string | null;
  distance_km: number | null;
}

export interface Condition {
  id: string;
  name: string;
  diagnosed_date: string | null;
  notes: string | null;
}

export interface Doctor {
  id: string;
  name: string | null;
  phone: string;
  specialization: string | null;
  license_no: string | null;
  clinic_name?: string | null;
  clinic_address?: string | null;
  consultation_fee_inr?: number | null;
  languages?: string | null;
  profile_completed?: boolean;
  created_at: string;
}

export interface Appointment {
  id: string;
  patient_id: string;
  doctor_id: string;
  /** 24-hour, "17:30". Use time_slot_label for display. */
  time_slot: string;
  time_slot_label?: string | null;
  date: string;
  status: "pending" | "confirmed" | "cancelled" | "completed" | string;
  notes: string | null;
  doctor_notes?: string | null;
  created_by?: string | null;
  cancelled_by?: string | null;
  is_past?: boolean;
  created_at: string;
  doctor?: Doctor;
  patient?: Patient;
}

export interface Slot {
  time_slot: string;
  available: boolean;
  reason?: string | null;
}

export interface DaySlots {
  date: string;
  slots: Slot[];
  /** Why the day yields nothing — "Dr X does not hold clinic on Sundays". */
  closed_reason?: string | null;
}

export interface Availability {
  id: string;
  doctor_id: string;
  weekday: number;        // 0 = Monday
  start_time: string;     // "09:00"
  end_time: string;       // "13:00"
  slot_minutes: number;
  active: boolean;
}

export interface TimeOff {
  id: string;
  doctor_id: string;
  date: string;
  reason: string | null;
}

export interface SummaryFact {
  label: string;
  detail: string;
  tone: "neutral" | "good" | "warn" | "bad" | string;
}

export interface PatientSummary {
  patient_id: string;
  patient_name: string | null;
  age_years: number | null;
  narrative: string;
  /** "model" or "deterministic" — shown so a doctor knows who wrote the prose. */
  narrative_source: string;
  highlights: SummaryFact[];
  medicines: {
    id: string;
    raw_name: string;
    generic_name: string | null;
    dosage: string | null;
    frequency: string | null;
    instructions: string | null;
    has_safety_data: boolean;
  }[];
  safety_flags: {
    kind: string;
    severity: string;
    title: string;
    detail: string;
    source?: string | null;
    medicine?: string | null;
  }[];
  vitals: {
    metric: string;
    latest_value: number | null;
    latest_secondary: number | null;
    unit: string;
    band_label: string | null;
    band_tone: string | null;
    latest_at: string | null;
    count: number;
    average: number | null;
  }[];
  adherence: {
    percent: number;
    doses_taken: number;
    doses_expected: number;
    below_target: boolean;
  } | null;
  last_seen: string | null;
  generated_at: string;
}

export interface RecordEdit {
  id: string;
  field: string;
  old_value: string | null;
  new_value: string | null;
  reason: string | null;
  created_at: string;
  doctor_name: string | null;
}

export interface DoctorPatientSummary {
  id: string;
  name: string | null;
  phone: string;
  gender: string | null;
  blood_group: string | null;
  is_pregnant: boolean;
  last_appointment: string;
  last_status: string;
}

