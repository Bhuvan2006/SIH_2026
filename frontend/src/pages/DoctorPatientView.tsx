import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  api,
  type Allergy,
  type Appointment,
  type Condition,
  type Patient,
  type PatientSummary,
  type RecordEdit,
} from "../api/client";
import { Badge, Button, Card, EmptyState, Modal, Spinner } from "../components/ui";

interface SurgeryRow {
  id: string;
  name: string;
  year: string | null;
  hospital: string | null;
  notes: string | null;
}

interface RecordBundle {
  patient: Patient;
  allergies: Allergy[];
  conditions: Condition[];
  surgeries: SurgeryRow[];
  medications: {
    id: string;
    raw_name: string;
    dosage: string | null;
    frequency: string | null;
    instructions: string | null;
  }[];
  appointments: Appointment[];
}

const TONE_VARIANT: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  good: "success",
  warn: "warning",
  bad: "danger",
  neutral: "neutral",
};

type Tab = "summary" | "record" | "history";

export default function DoctorPatientView() {
  const { id } = useParams();
  const [tab, setTab] = useState<Tab>("summary");

  const [data, setData] = useState<RecordBundle | null>(null);
  const [summary, setSummary] = useState<PatientSummary | null>(null);
  const [edits, setEdits] = useState<RecordEdit[]>([]);

  const [loading, setLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [accessDenied, setAccessDenied] = useState(false);
  const [saving, setSaving] = useState(false);

  // Edit form
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    blood_group: "",
    height_cm: "",
    weight_kg: "",
    date_of_birth: "",
    gender: "",
    implants_devices: "",
    emergency_notes: "",
    is_pregnant: false,
    pregnancy_due_date: "",
    is_breastfeeding: false,
    reason: "",
  });

  // Add-item forms
  const [newAllergy, setNewAllergy] = useState({ allergen: "", reaction: "", severity: "moderate" });
  const [newCondition, setNewCondition] = useState("");
  const [newSurgery, setNewSurgery] = useState({ name: "", year: "", hospital: "" });

  const loadRecord = useCallback(() => {
    return api
      .get<RecordBundle>(`/doctor/patients/${id}`)
      .then((res) => {
        setData(res.data);
        const p = res.data.patient;
        setForm({
          blood_group: p.blood_group ?? "",
          height_cm: p.height_cm != null ? String(p.height_cm) : "",
          weight_kg: p.weight_kg != null ? String(p.weight_kg) : "",
          date_of_birth: p.date_of_birth ?? "",
          gender: p.gender ?? "",
          implants_devices: p.implants_devices ?? "",
          emergency_notes: p.emergency_notes ?? "",
          is_pregnant: !!p.is_pregnant,
          pregnancy_due_date: p.pregnancy_due_date ?? "",
          is_breastfeeding: !!p.is_breastfeeding,
          reason: "",
        });
        setAccessDenied(false);
      })
      .catch(() => setAccessDenied(true))
      .finally(() => setLoading(false));
  }, [id]);

  const loadSummary = useCallback(() => {
    setSummaryLoading(true);
    return api
      .get<PatientSummary>(`/doctor/patients/${id}/summary`)
      .then((res) => setSummary(res.data))
      .catch(() => setSummary(null))
      .finally(() => setSummaryLoading(false));
  }, [id]);

  const loadEdits = useCallback(() => {
    api
      .get<RecordEdit[]>(`/doctor/patients/${id}/edits`)
      .then((res) => setEdits(res.data))
      .catch(() => setEdits([]));
  }, [id]);

  useEffect(() => {
    loadRecord();
    loadSummary();
    loadEdits();
  }, [loadRecord, loadSummary, loadEdits]);

  const afterChange = async () => {
    await loadRecord();
    loadEdits();
    // The summary is computed from the record, so a stale one would contradict
    // the edit the doctor just made.
    loadSummary();
  };

  const saveProfile = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.patch(`/doctor/patients/${id}`, {
        blood_group: form.blood_group || null,
        height_cm: form.height_cm ? Number(form.height_cm) : null,
        weight_kg: form.weight_kg ? Number(form.weight_kg) : null,
        date_of_birth: form.date_of_birth || null,
        gender: form.gender || null,
        implants_devices: form.implants_devices || null,
        emergency_notes: form.emergency_notes || null,
        is_pregnant: form.is_pregnant,
        pregnancy_due_date: form.pregnancy_due_date || null,
        is_breastfeeding: form.is_breastfeeding,
        reason: form.reason || null,
      });
      setEditing(false);
      await afterChange();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Could not save those changes.");
    } finally {
      setSaving(false);
    }
  };

  const addAllergy = async () => {
    if (!newAllergy.allergen.trim()) return;
    await api.post(`/doctor/patients/${id}/allergies`, newAllergy);
    setNewAllergy({ allergen: "", reaction: "", severity: "moderate" });
    afterChange();
  };

  const removeAllergy = async (allergyId: string) => {
    await api.delete(`/doctor/patients/${id}/allergies/${allergyId}`);
    afterChange();
  };

  const addCondition = async () => {
    if (!newCondition.trim()) return;
    await api.post(`/doctor/patients/${id}/conditions`, { name: newCondition.trim() });
    setNewCondition("");
    afterChange();
  };

  const removeCondition = async (conditionId: string) => {
    await api.delete(`/doctor/patients/${id}/conditions/${conditionId}`);
    afterChange();
  };

  const addSurgery = async () => {
    if (!newSurgery.name.trim()) return;
    await api.post(`/doctor/patients/${id}/surgeries`, {
      name: newSurgery.name.trim(),
      year: newSurgery.year || null,
      hospital: newSurgery.hospital || null,
    });
    setNewSurgery({ name: "", year: "", hospital: "" });
    afterChange();
  };

  const removeSurgery = async (surgeryId: string) => {
    await api.delete(`/doctor/patients/${id}/surgeries/${surgeryId}`);
    afterChange();
  };

  if (loading) return <Spinner label="Loading patient…" />;

  if (accessDenied) {
    return (
      <div className="animate-in">
        <Link to="/doctor" className="btn-link">
          ← Back to dashboard
        </Link>
        <EmptyState
          icon="🔒"
          title="Record not available"
          description="A doctor can only open the record of a patient who has an appointment with them."
        />
      </div>
    );
  }

  if (!data) return <p>Patient not found.</p>;
  const p = data.patient;

  return (
    <div className="doctor-patient animate-in">
      <Link to="/doctor" className="btn-link">
        ← Back to dashboard
      </Link>

      <div className="wsection__head">
        <div>
          <h1>{p.name || "Unnamed patient"}</h1>
          <p className="hint">
            {[
              summary?.age_years ? `${summary.age_years} years` : null,
              p.gender,
              p.blood_group ? `Blood group ${p.blood_group}` : "Blood group not recorded",
              p.phone,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <Button onClick={() => setEditing(true)}>Edit record</Button>
      </div>

      {p.is_pregnant && (
        <p className="preg-banner">
          🤰 <strong>Pregnant</strong>
          {p.pregnancy_due_date ? ` · due ${p.pregnancy_due_date}` : ""} — check every prescription
          against pregnancy contraindications.
        </p>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <div className="tabbar" role="tablist">
        {(
          [
            ["summary", "Summary"],
            ["record", "Full record"],
            ["history", `Change history (${edits.length})`],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            className={`tabbar__tab ${tab === key ? "tabbar__tab--on" : ""}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ------------------------------------------------------- summary --- */}
      {tab === "summary" &&
        (summaryLoading ? (
          <Spinner label="Preparing summary…" />
        ) : !summary ? (
          <p className="hint">Could not build a summary for this patient.</p>
        ) : (
          <>
            <Card className="summary-card">
              <p className="summary-card__text">{summary.narrative}</p>
              <p className="summary-card__source">
                {summary.narrative_source === "model"
                  ? "Narrative written by an AI model from the facts below. The lists and figures are computed, not generated — but read the record before acting."
                  : "Written from the record. The AI narrative was unavailable, so this is the plain computed summary."}
              </p>
            </Card>

            {summary.highlights.length > 0 && (
              <section className="wsection">
                <h2 className="wsection__title">What matters today</h2>
                <div className="hl-grid">
                  {summary.highlights.map((h, i) => (
                    <Card key={i} className={`hl hl--${h.tone}`}>
                      <div className="hl__head">
                        <strong>{h.label}</strong>
                        {h.tone !== "neutral" && (
                          <Badge variant={TONE_VARIANT[h.tone] ?? "neutral"}>{h.tone}</Badge>
                        )}
                      </div>
                      <p className="hl__detail">{h.detail}</p>
                    </Card>
                  ))}
                </div>
              </section>
            )}

            {summary.safety_flags.length > 0 && (
              <section className="wsection">
                <h2 className="wsection__title">
                  Flags on current medicines ({summary.safety_flags.length})
                </h2>
                <div className="appt-list">
                  {summary.safety_flags.map((f, i) => (
                    <Card key={i} className={`hl hl--${f.severity === "critical" ? "bad" : "warn"}`}>
                      <div className="hl__head">
                        <strong>{f.title}</strong>
                        <Badge variant={f.severity === "critical" ? "danger" : "warning"}>
                          {f.severity}
                        </Badge>
                      </div>
                      {f.medicine && <p className="hint">Raised by: {f.medicine}</p>}
                      <p className="hl__detail">{f.detail}</p>
                      {f.source && <p className="hint">Source: {f.source}</p>}
                    </Card>
                  ))}
                </div>
              </section>
            )}

            <section className="wsection">
              <h2 className="wsection__title">Adherence &amp; vitals</h2>
              <div className="insights__strip">
                <Card className={`icard ${summary.adherence?.below_target ? "icard--alert" : ""}`}>
                  <p className="icard__label">Doses taken (30 days)</p>
                  <p className="icard__big">
                    {summary.adherence ? `${summary.adherence.percent}%` : "—"}
                  </p>
                  <p className="icard__sub">
                    {summary.adherence
                      ? `${summary.adherence.doses_taken} of ${summary.adherence.doses_expected}`
                      : "No reminder history"}
                  </p>
                </Card>
                {summary.vitals.map((v) => (
                  <Card key={v.metric} className="icard">
                    <p className="icard__label">{v.metric.replace(/_/g, " ")}</p>
                    <p className="icard__big">
                      {v.latest_value}
                      {v.latest_secondary ? `/${v.latest_secondary}` : ""}
                      <span className="icard__bigunit"> {v.unit}</span>
                    </p>
                    <p className="icard__sub">
                      {v.band_label ?? `${v.count} readings`}
                      {v.latest_at ? ` · ${v.latest_at.slice(0, 10)}` : ""}
                    </p>
                  </Card>
                ))}
              </div>
            </section>
          </>
        ))}

      {/* -------------------------------------------------- full record --- */}
      {tab === "record" && (
        <>
          <section className="wsection">
            <h2 className="wsection__title">Conditions</h2>
            {data.conditions.length === 0 ? (
              <p className="hint">None recorded.</p>
            ) : (
              <ul className="session-list">
                {data.conditions.map((c) => (
                  <li key={c.id}>
                    <span>
                      <strong>{c.name.replace(/_/g, " ")}</strong>
                      {c.notes ? <span className="hint"> · {c.notes}</span> : null}
                    </span>
                    <Button variant="link" onClick={() => removeCondition(c.id)}>
                      Remove
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            <div className="inline-add">
              <input
                value={newCondition}
                placeholder="Add a condition (e.g. hypothyroidism)"
                onChange={(e) => setNewCondition(e.target.value)}
              />
              <Button variant="secondary" onClick={addCondition}>
                Add
              </Button>
            </div>
          </section>

          <section className="wsection">
            <h2 className="wsection__title">Allergies</h2>
            {data.allergies.length === 0 ? (
              <p className="hint">None recorded.</p>
            ) : (
              <ul className="session-list">
                {data.allergies.map((a) => (
                  <li key={a.id}>
                    <span>
                      <strong>{a.allergen}</strong>
                      <span className="hint">
                        {a.reaction ? ` · ${a.reaction}` : ""} · {a.severity}
                      </span>
                    </span>
                    <Button variant="link" onClick={() => removeAllergy(a.id)}>
                      Remove
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            {/* Removing an allergy switches off a safety check, so the trail
                keeps what was deleted — see the change history tab. */}
            <div className="inline-add">
              <input
                value={newAllergy.allergen}
                placeholder="Allergen"
                onChange={(e) => setNewAllergy({ ...newAllergy, allergen: e.target.value })}
              />
              <input
                value={newAllergy.reaction}
                placeholder="Reaction"
                onChange={(e) => setNewAllergy({ ...newAllergy, reaction: e.target.value })}
              />
              <select
                value={newAllergy.severity}
                onChange={(e) => setNewAllergy({ ...newAllergy, severity: e.target.value })}
              >
                {["mild", "moderate", "severe", "anaphylaxis", "unknown"].map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              <Button variant="secondary" onClick={addAllergy}>
                Add
              </Button>
            </div>
          </section>

          <section className="wsection">
            <h2 className="wsection__title">Surgical history</h2>
            {data.surgeries.length === 0 ? (
              <p className="hint">None recorded.</p>
            ) : (
              <ul className="session-list">
                {data.surgeries.map((s) => (
                  <li key={s.id}>
                    <span>
                      <strong>{s.name}</strong>
                      <span className="hint">
                        {s.year ? ` · ${s.year}` : ""}
                        {s.hospital ? ` · ${s.hospital}` : ""}
                      </span>
                    </span>
                    <Button variant="link" onClick={() => removeSurgery(s.id)}>
                      Remove
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            <div className="inline-add">
              <input
                value={newSurgery.name}
                placeholder="Procedure"
                onChange={(e) => setNewSurgery({ ...newSurgery, name: e.target.value })}
              />
              <input
                value={newSurgery.year}
                placeholder="Year"
                onChange={(e) => setNewSurgery({ ...newSurgery, year: e.target.value })}
              />
              <input
                value={newSurgery.hospital}
                placeholder="Hospital"
                onChange={(e) => setNewSurgery({ ...newSurgery, hospital: e.target.value })}
              />
              <Button variant="secondary" onClick={addSurgery}>
                Add
              </Button>
            </div>
          </section>

          <section className="wsection">
            <h2 className="wsection__title">Current medicines</h2>
            {data.medications.length === 0 ? (
              <p className="hint">None recorded.</p>
            ) : (
              <table className="meds-table">
                <thead>
                  <tr>
                    <th>Medicine</th>
                    <th>Dose &amp; frequency</th>
                    <th>Instructions</th>
                  </tr>
                </thead>
                <tbody>
                  {data.medications.map((m) => (
                    <tr key={m.id}>
                      <td>
                        <strong>{m.raw_name}</strong>
                      </td>
                      <td>
                        {[m.dosage, m.frequency].filter(Boolean).join(" · ") || "—"}
                      </td>
                      <td>{m.instructions ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="hint">
              Medicines come from the patient's confirmed prescriptions. Arogya never changes a
              prescription — record changes in your consultation note instead.
            </p>
          </section>

          <section className="wsection">
            <h2 className="wsection__title">Your appointments with this patient</h2>
            {data.appointments.length === 0 ? (
              <p className="hint">None yet.</p>
            ) : (
              <ul className="session-list">
                {data.appointments.map((a) => (
                  <li key={a.id}>
                    <span>
                      <strong>
                        {a.date} {a.time_slot_label ?? a.time_slot}
                      </strong>
                      {a.notes ? <span className="hint"> · {a.notes}</span> : null}
                      {a.doctor_notes ? (
                        <div className="hint">Your note: {a.doctor_notes}</div>
                      ) : null}
                    </span>
                    <Badge
                      variant={
                        a.status === "completed"
                          ? "neutral"
                          : a.status === "cancelled"
                            ? "danger"
                            : "success"
                      }
                    >
                      {a.status}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}

      {/* ------------------------------------------------ change history --- */}
      {tab === "history" && (
        <section className="wsection">
          <p className="hint">
            Every change a doctor makes to this record is kept here, including changes by other
            doctors. Nothing removes an entry.
          </p>
          {edits.length === 0 ? (
            <EmptyState
              icon="📝"
              title="No changes yet"
              description="This record is exactly as the patient entered it."
            />
          ) : (
            <ul className="session-list">
              {edits.map((e) => (
                <li key={e.id}>
                  <span>
                    <strong>{e.field.replace(/[._]/g, " ")}</strong>
                    <span className="hint">
                      {" "}
                      {e.old_value ?? "(empty)"} → {e.new_value ?? "(removed)"}
                    </span>
                    <div className="hint">
                      {e.doctor_name ?? "A doctor"} · {new Date(e.created_at).toLocaleString()}
                      {e.reason ? ` · ${e.reason}` : ""}
                    </div>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {editing && (
        <Modal isOpen title="Edit patient record" onClose={() => setEditing(false)}>
          <div className="book-form">
            <p className="hint">
              Corrections are recorded against your name with the reason you give. The patient's
              phone, language and insurance details are theirs to change, not yours.
            </p>

            <label htmlFor="ep-blood">Blood group</label>
            <input
              id="ep-blood"
              value={form.blood_group}
              onChange={(e) => setForm({ ...form, blood_group: e.target.value })}
              placeholder="B+"
            />

            <label htmlFor="ep-dob">Date of birth</label>
            <input
              id="ep-dob"
              type="date"
              value={form.date_of_birth}
              onChange={(e) => setForm({ ...form, date_of_birth: e.target.value })}
            />

            <label htmlFor="ep-gender">Gender</label>
            <input
              id="ep-gender"
              value={form.gender}
              onChange={(e) => setForm({ ...form, gender: e.target.value })}
            />

            <label htmlFor="ep-height">Height (cm)</label>
            <input
              id="ep-height"
              type="number"
              value={form.height_cm}
              onChange={(e) => setForm({ ...form, height_cm: e.target.value })}
            />

            <label htmlFor="ep-weight">Weight (kg)</label>
            <input
              id="ep-weight"
              type="number"
              value={form.weight_kg}
              onChange={(e) => setForm({ ...form, weight_kg: e.target.value })}
            />

            <label htmlFor="ep-implants">Implants / devices</label>
            <input
              id="ep-implants"
              value={form.implants_devices}
              onChange={(e) => setForm({ ...form, implants_devices: e.target.value })}
              placeholder="Pacemaker, stent, insulin pump…"
            />

            <label className="checkline">
              <input
                type="checkbox"
                checked={form.is_pregnant}
                onChange={(e) => setForm({ ...form, is_pregnant: e.target.checked })}
              />
              <span>Pregnant</span>
            </label>

            {form.is_pregnant && (
              <>
                <label htmlFor="ep-due">Expected due date</label>
                <input
                  id="ep-due"
                  type="date"
                  value={form.pregnancy_due_date}
                  onChange={(e) => setForm({ ...form, pregnancy_due_date: e.target.value })}
                />
              </>
            )}

            <label className="checkline">
              <input
                type="checkbox"
                checked={form.is_breastfeeding}
                onChange={(e) => setForm({ ...form, is_breastfeeding: e.target.checked })}
              />
              <span>Breastfeeding</span>
            </label>

            <label htmlFor="ep-notes">Emergency notes</label>
            <textarea
              id="ep-notes"
              rows={3}
              value={form.emergency_notes}
              onChange={(e) => setForm({ ...form, emergency_notes: e.target.value })}
            />

            <label htmlFor="ep-reason">Why are you changing this?</label>
            <input
              id="ep-reason"
              value={form.reason}
              placeholder="e.g. corrected from lab report"
              onChange={(e) => setForm({ ...form, reason: e.target.value })}
            />

            <Button onClick={saveProfile} disabled={saving}>
              {saving ? "Saving…" : "Save changes"}
            </Button>
          </div>
        </Modal>
      )}
    </div>
  );
}
