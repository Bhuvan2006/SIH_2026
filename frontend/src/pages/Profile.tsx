import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  ALLERGY_SEVERITIES,
  BLOOD_GROUPS,
  type Allergy,
  type Condition,
  type EmergencyContact,
  type Patient,
  type Surgery,
} from "../api/client";
import { useAuth } from "../context/AuthContext";
import { Alert, Badge, Button, Card, EmptyState, Spinner, TextField } from "../components/ui";

const CONDITION_OPTIONS = [
  { value: "diabetes_type_2", label: "Type 2 diabetes" },
  { value: "diabetes_type_1", label: "Type 1 diabetes" },
  { value: "hypertension", label: "High blood pressure" },
  { value: "dyslipidemia", label: "High cholesterol" },
  { value: "hypothyroidism", label: "Thyroid (hypothyroidism)" },
  { value: "ckd", label: "Kidney disease" },
  { value: "asthma", label: "Asthma" },
];

export default function Profile() {
  const navigate = useNavigate();
  const { refreshPatient } = useAuth();

  const [form, setForm] = useState<Partial<Patient>>({});
  const [allergies, setAllergies] = useState<Allergy[]>([]);
  const [contacts, setContacts] = useState<EmergencyContact[]>([]);
  const [conditions, setConditions] = useState<Condition[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // New-entry drafts
  const [allergen, setAllergen] = useState("");
  const [reaction, setReaction] = useState("");
  const [severity, setSeverity] = useState("unknown");
  const [contactName, setContactName] = useState("");
  const [contactRel, setContactRel] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [customCondition, setCustomCondition] = useState("");
  const [customConditionNote, setCustomConditionNote] = useState("");
  const [surgeries, setSurgeries] = useState<Surgery[]>([]);
  const [surgeryName, setSurgeryName] = useState("");
  const [surgeryYear, setSurgeryYear] = useState("");
  const [surgeryHospital, setSurgeryHospital] = useState("");

  useEffect(() => {
    Promise.all([
      api.get<Patient>("/patients/me"),
      api.get<Allergy[]>("/patients/me/allergies"),
      api.get<EmergencyContact[]>("/patients/me/emergency-contacts"),
      api.get<Condition[]>("/patients/me/conditions"),
      api.get<Surgery[]>("/patients/me/surgeries"),
    ])
      .then(([p, a, c, cond, surg]) => {
        setForm(p.data);
        setAllergies(a.data);
        setContacts(c.data);
        setConditions(cond.data);
        setSurgeries(surg.data);
      })
      .catch(() => setError("Could not load your profile. Please refresh."))
      .finally(() => setLoading(false));
  }, []);

  const set = <K extends keyof Patient>(key: K, value: Patient[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    setSaved(false);
  };

  const saveProfile = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.patch("/patients/me", { ...form, profile_completed: true });
      await refreshPatient();
      setSaved(true);
    } catch {
      setError("Could not save your profile. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const addAllergy = async () => {
    if (!allergen.trim()) return;
    const res = await api.post<Allergy>("/patients/me/allergies", {
      allergen: allergen.trim(),
      reaction: reaction.trim() || null,
      severity,
    });
    setAllergies((prev) => [...prev, res.data]);
    setAllergen("");
    setReaction("");
    setSeverity("unknown");
  };

  const removeAllergy = async (id: string) => {
    await api.delete(`/patients/me/allergies/${id}`);
    setAllergies((prev) => prev.filter((a) => a.id !== id));
  };

  const addContact = async () => {
    if (!contactName.trim() || !contactPhone.trim()) return;
    const res = await api.post<EmergencyContact>("/patients/me/emergency-contacts", {
      name: contactName.trim(),
      relationship_to_patient: contactRel.trim() || null,
      phone: contactPhone.trim(),
      is_primary: contacts.length === 0,
    });
    setContacts((prev) => [...prev, res.data]);
    setContactName("");
    setContactRel("");
    setContactPhone("");
  };

  const removeContact = async (id: string) => {
    await api.delete(`/patients/me/emergency-contacts/${id}`);
    setContacts((prev) => prev.filter((c) => c.id !== id));
  };

  const toggleCondition = async (value: string, label: string) => {
    const existing = conditions.find((c) => c.name === value);
    if (existing) {
      await api.delete(`/patients/me/conditions/${existing.id}`);
      setConditions((prev) => prev.filter((c) => c.id !== existing.id));
      return;
    }
    const res = await api.post<Condition>("/patients/me/conditions", { name: value, notes: label });
    setConditions((prev) => [...prev, res.data]);
  };

  const addCustomCondition = async () => {
    const name = customCondition.trim();
    if (!name) return;
    const res = await api.post<Condition>("/patients/me/conditions", {
      name,
      notes: customConditionNote.trim() || null,
    });
    setConditions((prev) => [...prev, res.data]);
    setCustomCondition("");
    setCustomConditionNote("");
  };

  const removeCondition = async (id: string) => {
    await api.delete(`/patients/me/conditions/${id}`);
    setConditions((prev) => prev.filter((c) => c.id !== id));
  };

  const addSurgery = async () => {
    if (!surgeryName.trim()) return;
    const res = await api.post<Surgery>("/patients/me/surgeries", {
      name: surgeryName.trim(),
      year: surgeryYear.trim() || null,
      hospital: surgeryHospital.trim() || null,
    });
    setSurgeries((prev) => [...prev, res.data]);
    setSurgeryName("");
    setSurgeryYear("");
    setSurgeryHospital("");
  };

  const removeSurgery = async (id: string) => {
    await api.delete(`/patients/me/surgeries/${id}`);
    setSurgeries((prev) => prev.filter((s) => s.id !== id));
  };

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: "center" }}>
        <Spinner size="lg" label="Loading your profile…" />
      </div>
    );
  }

  return (
    <div>
      <div className="dash-hero animate-in">
        <h1>Your health profile</h1>
        <p>
          This is what powers your emergency QR code and lets Arogya answer questions about your own
          medicines. Fill in what you can — you can always come back.
        </p>
      </div>

      {error && <Alert variant="danger">{error}</Alert>}
      {saved && <Alert variant="success">Profile saved.</Alert>}

      <form onSubmit={saveProfile}>
        <Card title="About you">
          <div className="form-grid">
            <TextField
              label="Full name"
              value={form.name ?? ""}
              onChange={(e) => set("name", e.target.value)}
              autoComplete="name"
            />
            <TextField
              label="Date of birth"
              type="date"
              value={form.date_of_birth ?? ""}
              onChange={(e) => set("date_of_birth", e.target.value)}
            />
            <div className="ui-field">
              <label className="ui-field__label" htmlFor="gender">
                Gender
              </label>
              <select
                id="gender"
                className="ui-field__input"
                value={form.gender ?? ""}
                onChange={(e) => set("gender", e.target.value)}
              >
                <option value="">Prefer not to say</option>
                <option value="female">Female</option>
                <option value="male">Male</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div className="ui-field">
              <label className="ui-field__label" htmlFor="blood_group">
                Blood group
              </label>
              <select
                id="blood_group"
                className="ui-field__input"
                value={form.blood_group ?? ""}
                onChange={(e) => set("blood_group", e.target.value)}
              >
                <option value="">Not known</option>
                {BLOOD_GROUPS.map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>
            </div>
            <TextField
              label="Height (cm)"
              type="number"
              value={form.height_cm ?? ""}
              onChange={(e) => set("height_cm", e.target.value ? Number(e.target.value) : null)}
            />
            <TextField
              label="Weight (kg)"
              type="number"
              value={form.weight_kg ?? ""}
              onChange={(e) => set("weight_kg", e.target.value ? Number(e.target.value) : null)}
            />
          </div>

          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={!!form.organ_donor}
              onChange={(e) => set("organ_donor", e.target.checked)}
            />
            <span>I am a registered organ donor</span>
          </label>

          {/* Pregnancy drives a hard red block on contraindicated medicines
              during prescription review, so it sits with the core profile
              rather than buried in a medical-history section. */}
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={!!form.is_pregnant}
              onChange={(e) => set("is_pregnant", e.target.checked)}
            />
            <span>I am pregnant</span>
          </label>
          {form.is_pregnant && (
            <div className="preg-box">
              <TextField
                label="Due date (optional)"
                type="date"
                value={form.pregnancy_due_date ?? ""}
                onChange={(e) => set("pregnancy_due_date", e.target.value)}
              />
              <p className="hint">
                While this is on, any prescribed medicine that shouldn&rsquo;t normally be taken in
                pregnancy is flagged in red when you scan a prescription. Turn it off after your
                pregnancy ends.
              </p>
            </div>
          )}
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={!!form.is_breastfeeding}
              onChange={(e) => set("is_breastfeeding", e.target.checked)}
            />
            <span>I am breastfeeding</span>
          </label>
        </Card>

        <Card title="Emergency medical details" className="stack-card">
          <p className="hint">
            These are the details a paramedic or ER doctor needs first. They appear on your emergency
            QR code.
          </p>
          <div className="form-grid">
            <TextField
              label="Implants or devices"
              placeholder="Pacemaker, stent, insulin pump…"
              value={form.implants_devices ?? ""}
              onChange={(e) => set("implants_devices", e.target.value)}
            />
            <TextField
              label="Anything else responders should know"
              placeholder="Hard of hearing, on dialysis…"
              value={form.emergency_notes ?? ""}
              onChange={(e) => set("emergency_notes", e.target.value)}
            />
            <TextField
              label="Doctor's name"
              value={form.primary_doctor_name ?? ""}
              onChange={(e) => set("primary_doctor_name", e.target.value)}
            />
            <TextField
              label="Doctor's phone"
              type="tel"
              value={form.primary_doctor_phone ?? ""}
              onChange={(e) => set("primary_doctor_phone", e.target.value)}
            />
            <TextField
              label="Insurance provider"
              value={form.insurance_provider ?? ""}
              onChange={(e) => set("insurance_provider", e.target.value)}
            />
            <TextField
              label="Policy number"
              value={form.insurance_policy_no ?? ""}
              onChange={(e) => set("insurance_policy_no", e.target.value)}
            />
          </div>
          <TextField
            label="Home address"
            value={form.address ?? ""}
            onChange={(e) => set("address", e.target.value)}
            autoComplete="street-address"
          />
        </Card>

        <div style={{ display: "flex", gap: 10, marginTop: 20, flexWrap: "wrap" }}>
          <Button type="submit" loading={saving} size="lg">
            Save profile
          </Button>
          <Button type="button" variant="ghost" size="lg" onClick={() => navigate("/emergency-card")}>
            View my emergency QR
          </Button>
        </div>
      </form>

      {/* ---------- Allergies ---------- */}
      <Card title="Allergies" className="stack-card">
        <p className="hint">
          Severity matters in an emergency — a severe or anaphylactic allergy is shown as a red alert
          on your emergency card.
        </p>

        {allergies.length === 0 ? (
          <EmptyState title="No allergies recorded" description="Add any drug or food allergies below." />
        ) : (
          <ul className="chip-list">
            {allergies.map((a) => (
              <li key={a.id} className="chip-row">
                <div>
                  <strong>{a.allergen}</strong>{" "}
                  <Badge
                    variant={
                      a.severity === "anaphylaxis" || a.severity === "severe"
                        ? "danger"
                        : a.severity === "moderate"
                          ? "warning"
                          : "neutral"
                    }
                  >
                    {a.severity}
                  </Badge>
                  {a.reaction && <div className="hint">{a.reaction}</div>}
                </div>
                <Button variant="ghost" size="sm" onClick={() => removeAllergy(a.id)}>
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}

        <div className="form-grid" style={{ marginTop: 14 }}>
          <TextField
            label="Allergen"
            placeholder="Penicillin"
            value={allergen}
            onChange={(e) => setAllergen(e.target.value)}
          />
          <TextField
            label="Reaction"
            placeholder="Rash, swelling…"
            value={reaction}
            onChange={(e) => setReaction(e.target.value)}
          />
          <div className="ui-field">
            <label className="ui-field__label" htmlFor="severity">
              Severity
            </label>
            <select
              id="severity"
              className="ui-field__input"
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
            >
              {ALLERGY_SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        </div>
        <Button type="button" onClick={addAllergy} disabled={!allergen.trim()}>
          Add allergy
        </Button>
      </Card>

      {/* ---------- Emergency contacts ---------- */}
      <Card title="Emergency contacts" className="stack-card">
        {contacts.length === 0 ? (
          <EmptyState title="No contacts yet" description="Who should be called if something happens?" />
        ) : (
          <ul className="chip-list">
            {contacts.map((c) => (
              <li key={c.id} className="chip-row">
                <div>
                  <strong>{c.name}</strong> {c.is_primary && <Badge variant="primary">primary</Badge>}
                  <div className="hint">
                    {c.relationship_to_patient ? `${c.relationship_to_patient} · ` : ""}
                    {c.phone}
                  </div>
                </div>
                <Button variant="ghost" size="sm" onClick={() => removeContact(c.id)}>
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}

        <div className="form-grid" style={{ marginTop: 14 }}>
          <TextField
            label="Name"
            value={contactName}
            onChange={(e) => setContactName(e.target.value)}
          />
          <TextField
            label="Relationship"
            placeholder="Spouse, son…"
            value={contactRel}
            onChange={(e) => setContactRel(e.target.value)}
          />
          <TextField
            label="Phone"
            type="tel"
            value={contactPhone}
            onChange={(e) => setContactPhone(e.target.value)}
          />
        </div>
        <Button
          type="button"
          onClick={addContact}
          disabled={!contactName.trim() || !contactPhone.trim()}
        >
          Add contact
        </Button>
      </Card>

      {/* ---------- Conditions ---------- */}
      <Card title="Ongoing conditions" className="stack-card">
        <p className="hint">
          Used for diet guidance, to personalise chatbot answers, and to flag medicines that may
          not suit you. Tap to add or remove.
        </p>
        <div className="condition-options">
          {CONDITION_OPTIONS.map((opt) => {
            const active = conditions.some((c) => c.name === opt.value);
            return (
              <Button
                key={opt.value}
                type="button"
                size="sm"
                variant={active ? "primary" : "ghost"}
                onClick={() => toggleCondition(opt.value, opt.label)}
              >
                {active ? "✓ " : "+ "}
                {opt.label}
              </Button>
            );
          })}
        </div>

        {/* Anything the patient has that isn't in the common list. The
            preset buttons cover the frequent cases; this makes sure nobody
            is stuck unable to record their actual diagnosis. */}
        <div className="form-grid" style={{ marginTop: 16 }}>
          <TextField
            label="Add another condition"
            placeholder="e.g. Rheumatoid arthritis"
            value={customCondition}
            onChange={(e) => setCustomCondition(e.target.value)}
          />
          <TextField
            label="Note (optional)"
            placeholder="Diagnosed 2020, under Dr. Rao"
            value={customConditionNote}
            onChange={(e) => setCustomConditionNote(e.target.value)}
          />
        </div>
        <Button type="button" onClick={addCustomCondition} disabled={!customCondition.trim()}>
          Add condition
        </Button>

        {conditions.filter((c) => !CONDITION_OPTIONS.some((o) => o.value === c.name)).length > 0 && (
          <ul className="chip-list" style={{ marginTop: 14 }}>
            {conditions
              .filter((c) => !CONDITION_OPTIONS.some((o) => o.value === c.name))
              .map((c) => (
                <li key={c.id} className="chip-row">
                  <div>
                    <strong>{c.name}</strong>
                    {c.notes && <div className="hint">{c.notes}</div>}
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => removeCondition(c.id)}>
                    Remove
                  </Button>
                </li>
              ))}
          </ul>
        )}
      </Card>

      {/* ---------- Surgeries ---------- */}
      <Card title="Past surgeries and procedures" className="stack-card">
        <p className="hint">
          Surgeons and anaesthetists ask about these specifically, and they appear on your emergency
          card — knowing about a stent or a removed organ changes emergency treatment.
        </p>

        {surgeries.length === 0 ? (
          <EmptyState
            title="None recorded"
            description="Add any operation you've had, even years ago."
          />
        ) : (
          <ul className="chip-list">
            {surgeries.map((s) => (
              <li key={s.id} className="chip-row">
                <div>
                  <strong>{s.name}</strong>
                  {s.year && <Badge variant="neutral">{s.year}</Badge>}
                  {s.hospital && <div className="hint">{s.hospital}</div>}
                </div>
                <Button variant="ghost" size="sm" onClick={() => removeSurgery(s.id)}>
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}

        <div className="form-grid" style={{ marginTop: 14 }}>
          <TextField
            label="Operation"
            placeholder="Appendectomy"
            value={surgeryName}
            onChange={(e) => setSurgeryName(e.target.value)}
          />
          <TextField
            label="Year"
            placeholder="2019"
            value={surgeryYear}
            onChange={(e) => setSurgeryYear(e.target.value)}
          />
          <TextField
            label="Hospital (optional)"
            value={surgeryHospital}
            onChange={(e) => setSurgeryHospital(e.target.value)}
          />
        </div>
        <Button type="button" onClick={addSurgery} disabled={!surgeryName.trim()}>
          Add surgery
        </Button>
      </Card>
    </div>
  );
}
