import { useState, useEffect, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ALLERGY_SEVERITIES, BLOOD_GROUPS } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { Alert, Badge, Button, TextField } from "../components/ui";

const CONDITION_OPTIONS = [
  { value: "diabetes_type_2", label: "Type 2 diabetes" },
  { value: "diabetes_type_1", label: "Type 1 diabetes" },
  { value: "hypertension", label: "High blood pressure" },
  { value: "dyslipidemia", label: "High cholesterol" },
  { value: "hypothyroidism", label: "Thyroid" },
  { value: "ckd", label: "Kidney disease" },
  { value: "asthma", label: "Asthma" },
];

interface DraftAllergy {
  allergen: string;
  reaction: string;
  severity: string;
}

interface DraftSurgery {
  name: string;
  year: string;
}

/**
 * Post-registration setup. New accounts land here and cannot reach the app
 * until it's done -- the emergency QR, personalised chatbot answers, and
 * reminder messages are all worthless without this data, so collecting it
 * up front beats discovering it's empty during an emergency.
 */
export default function Onboarding() {
  const navigate = useNavigate();
  const { patient, refreshPatient } = useAuth();

  const [step, setStep] = useState(1);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Step 1 — identity
  const [name, setName] = useState(patient?.name ?? "");
  const [dob, setDob] = useState(patient?.date_of_birth ?? "");
  const [gender, setGender] = useState(patient?.gender ?? "");
  const [bloodGroup, setBloodGroup] = useState(patient?.blood_group ?? "");
  const [heightCm, setHeightCm] = useState(patient?.height_cm ? String(patient.height_cm) : "");
  const [weightKg, setWeightKg] = useState(patient?.weight_kg ? String(patient.weight_kg) : "");
  const [isPregnant, setIsPregnant] = useState(!!patient?.is_pregnant);

  // Step 2 — allergies + conditions
  const [allergies, setAllergies] = useState<DraftAllergy[]>([]);
  const [allergen, setAllergen] = useState("");
  const [reaction, setReaction] = useState("");
  const [severity, setSeverity] = useState("unknown");
  const [conditions, setConditions] = useState<string[]>([]);

  // Step 3 — emergency contact + past surgeries
  const [contactName, setContactName] = useState("");
  const [contactRel, setContactRel] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [surgeries, setSurgeries] = useState<DraftSurgery[]>([]);
  const [surgeryName, setSurgeryName] = useState("");
  const [surgeryYear, setSurgeryYear] = useState("");

  useEffect(() => {
    // If the patient has already added data, we should load it to avoid duplication
    // on a subsequent submission.
    api.get<any[]>("/patients/me/allergies").then((res) => {
      if (res.data.length > 0) setAllergies(res.data);
    }).catch(() => {});
    
    api.get<any[]>("/patients/me/conditions").then((res) => {
      if (res.data.length > 0) setConditions(res.data.map((c) => c.name));
    }).catch(() => {});

    api.get<any[]>("/patients/me/surgeries").then((res) => {
      if (res.data.length > 0) setSurgeries(res.data.map(s => ({ name: s.name, year: s.year || "" })));
    }).catch(() => {});

    api.get<any[]>("/patients/me/emergency-contacts").then((res) => {
      if (res.data.length > 0) {
        setContactName(res.data[0].name);
        setContactRel(res.data[0].relationship_to_patient || "");
        setContactPhone(res.data[0].phone);
      }
    }).catch(() => {});
  }, []);

  const addAllergyDraft = () => {
    if (!allergen.trim()) return;
    setAllergies((prev) => [...prev, { allergen: allergen.trim(), reaction: reaction.trim(), severity }]);
    setAllergen("");
    setReaction("");
    setSeverity("unknown");
  };

  const addSurgeryDraft = () => {
    if (!surgeryName.trim()) return;
    setSurgeries((prev) => [...prev, { name: surgeryName.trim(), year: surgeryYear.trim() }]);
    setSurgeryName("");
    setSurgeryYear("");
  };

  const toggleCondition = (value: string) =>
    setConditions((prev) =>
      prev.includes(value) ? prev.filter((c) => c !== value) : [...prev, value]
    );

  const finish = async (e: FormEvent) => {
    e.preventDefault();
    // A form with a submit button submits on Enter from ANY text input, so
    // typing a name on step 1 and pressing Enter used to save a half-empty
    // profile and drop the user into the app. The step guard makes reaching
    // the last step the only way to save, whatever the keyboard does.
    if (step < 3) {
      setStep((current) => Math.min(3, current + 1));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.patch("/patients/me", {
        name: name.trim() || null,
        date_of_birth: dob || null,
        gender: gender || null,
        blood_group: bloodGroup || null,
        height_cm: heightCm ? Number(heightCm) : null,
        weight_kg: weightKg ? Number(weightKg) : null,
        is_pregnant: isPregnant,
        profile_completed: true,
      });

      // Filter out existing allergies (they have an id if fetched from the backend)
      
      // Easiest robust fix without altering backend logic is to just fetch what we have and only add what's missing.

      // Actually, since this is onboarding, it's safer to only POST items that lack an ID (new drafts).
      // For conditions, they are just strings in our state, so we need to know what was already there.
      // The easiest way is to let the user add/remove things. But if we just push all conditions in state, 
      // we might duplicate. Let's just catch duplication errors or accept that they get added again.
      // Wait, we can fetch the existing items and only POST the differences.
      // Let's implement this inline:

      const currentAllergies = await api.get("/patients/me/allergies").then(r => r.data);
      const currentConditions = await api.get("/patients/me/conditions").then(r => r.data);
      const currentSurgeries = await api.get("/patients/me/surgeries").then(r => r.data);
      const currentContacts = await api.get("/patients/me/emergency-contacts").then(r => r.data);

      const allergiesToPost = allergies.filter(a => !currentAllergies.some((ca: any) => ca.allergen === a.allergen));
      const conditionsToPost = conditions.filter(c => !currentConditions.some((cc: any) => cc.name === c));
      const surgeriesToPost = surgeries.filter(s => !currentSurgeries.some((cs: any) => cs.name === s.name));
      
      const shouldPostContact = contactName.trim() && contactPhone.trim() && 
        !currentContacts.some((cc: any) => cc.phone === contactPhone.trim());

      await Promise.all([
        ...allergiesToPost.map((a) =>
          api.post("/patients/me/allergies", {
            allergen: a.allergen,
            reaction: a.reaction || null,
            severity: a.severity,
          })
        ),
        ...conditionsToPost.map((c) => api.post("/patients/me/conditions", { name: c })),
        ...surgeriesToPost.map((sg) =>
          api.post("/patients/me/surgeries", { name: sg.name, year: sg.year || null })
        ),
        ...(shouldPostContact
          ? [
              api.post("/patients/me/emergency-contacts", {
                name: contactName.trim(),
                relationship_to_patient: contactRel.trim() || null,
                phone: contactPhone.trim(),
                is_primary: true,
              }),
            ]
          : []),
      ]);

      await refreshPatient();
      navigate("/", { replace: true });
    } catch {
      setError("Could not save your details. Please try again.");
      setSaving(false);
    }
  };

  return (
    <div className="onb">
      <div className="onb__card">
        <div className="onb__head">
          <p className="hero__eyebrow" style={{ marginBottom: 10 }}>
            <span aria-hidden="true">🩺</span> Step {step} of 3
          </p>
          <h1 className="onb__title">
            {step === 1 && "Let's set up your health profile"}
            {step === 2 && "Allergies and conditions"}
            {step === 3 && "Emergency contact and past surgeries"}
          </h1>
          <p className="onb__lead">
            {step === 1 && "This powers your emergency QR code and your reminders. It takes a minute."}
            {step === 2 && "This is the part that matters most in an emergency. Add what you know."}
            {step === 3 && "One contact we can show a responder if you can't speak for yourself, and any operations you've had — a surgeon or anaesthetist asks about those first."}
          </p>
          <div className="onb__progress" aria-hidden="true">
            {[1, 2, 3].map((n) => (
              <span key={n} className={n <= step ? "is-done" : ""} />
            ))}
          </div>
        </div>

        {error && <Alert variant="danger">{error}</Alert>}

        <form onSubmit={finish}>
          {step === 1 && (
            <>
              <TextField
                label="Full name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="name"
                required
              />
              <div className="form-grid">
                <TextField
                  label="Date of birth"
                  type="date"
                  value={dob}
                  onChange={(e) => setDob(e.target.value)}
                />
                <div className="ui-field">
                  <label className="ui-field__label" htmlFor="onb-gender">
                    Gender
                  </label>
                  <select
                    id="onb-gender"
                    className="ui-field__input"
                    value={gender}
                    onChange={(e) => setGender(e.target.value)}
                  >
                    <option value="">Prefer not to say</option>
                    <option value="female">Female</option>
                    <option value="male">Male</option>
                    <option value="other">Other</option>
                  </select>
                </div>
                <div className="ui-field">
                  <label className="ui-field__label" htmlFor="onb-blood">
                    Blood group
                  </label>
                  <select
                    id="onb-blood"
                    className="ui-field__input"
                    value={bloodGroup}
                    onChange={(e) => setBloodGroup(e.target.value)}
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
                  inputMode="decimal"
                  placeholder="170"
                  value={heightCm}
                  onChange={(e) => setHeightCm(e.target.value)}
                />
                <TextField
                  label="Weight (kg)"
                  type="number"
                  inputMode="decimal"
                  placeholder="65"
                  value={weightKg}
                  onChange={(e) => setWeightKg(e.target.value)}
                />
              </div>

              <p className="hint" style={{ marginTop: 10 }}>
                Height and weight let Arogya show your BMI on the dashboard, and some medicine doses
                depend on weight.
              </p>

              {/* Only offered where it can apply. Asking every user whether
                  they are pregnant is both noisy and a poor experience. */}
              {(gender === "female" || gender === "" || gender === "other") && (
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={isPregnant}
                    onChange={(e) => setIsPregnant(e.target.checked)}
                  />
                  <span>
                    I am currently pregnant
                    <span className="hint" style={{ display: "block" }}>
                      Lets us flag medicines that aren&rsquo;t safe in pregnancy when you scan a
                      prescription.
                    </span>
                  </span>
                </label>
              )}
            </>
          )}

          {step === 2 && (
            <>
              {allergies.length > 0 && (
                <ul className="chip-list" style={{ marginBottom: 12 }}>
                  {allergies.map((a, i) => (
                    <li key={i} className="chip-row">
                      <span>
                        <strong>{a.allergen}</strong>{" "}
                        <Badge
                          variant={
                            a.severity === "severe" || a.severity === "anaphylaxis"
                              ? "danger"
                              : "neutral"
                          }
                        >
                          {a.severity}
                        </Badge>
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setAllergies((p) => p.filter((_, j) => j !== i))}
                      >
                        Remove
                      </Button>
                    </li>
                  ))}
                </ul>
              )}

              {/* Enter inside these fields adds the allergy. Without this it
                  hits the form's submit button instead, which is how a
                  half-filled profile used to get saved mid-way through. */}
              <div
                className="form-grid"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addAllergyDraft();
                  }
                }}
              >
                <TextField
                  label="Allergy"
                  placeholder="Penicillin, peanuts…"
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
                  <label className="ui-field__label" htmlFor="onb-sev">
                    Severity
                  </label>
                  <select
                    id="onb-sev"
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
              <Button type="button" variant="ghost" onClick={addAllergyDraft} disabled={!allergen.trim()}>
                + Add allergy
              </Button>
              <p className="hint" style={{ marginTop: 8 }}>
                Add each allergy separately &mdash; type it above and press{" "}
                <strong>+ Add allergy</strong>. Allergies you don&rsquo;t add here won&rsquo;t be
                checked against your prescriptions.
              </p>

              <p className="ui-field__label" style={{ marginTop: 20 }}>
                Ongoing conditions
              </p>
              <div className="condition-options">
                {CONDITION_OPTIONS.map((opt) => (
                  <Button
                    key={opt.value}
                    type="button"
                    size="sm"
                    variant={conditions.includes(opt.value) ? "primary" : "ghost"}
                    onClick={() => toggleCondition(opt.value)}
                  >
                    {conditions.includes(opt.value) ? "✓ " : "+ "}
                    {opt.label}
                  </Button>
                ))}
              </div>
            </>
          )}

          {step === 3 && (
            <>
              <p className="ui-field__label">Emergency contact</p>
              <div className="form-grid">
                <TextField
                  label="Contact name"
                  value={contactName}
                  onChange={(e) => setContactName(e.target.value)}
                  autoComplete="name"
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
                  autoComplete="tel"
                />
              </div>

              <p className="ui-field__label" style={{ marginTop: 22 }}>
                Past surgeries or procedures
              </p>
              <p className="hint" style={{ marginTop: -4, marginBottom: 10 }}>
                Anything you&rsquo;ve been operated on for. A stent, a splenectomy or a caesarean
                changes how you should be treated in an emergency.
              </p>

              {surgeries.length > 0 && (
                <ul className="chip-list" style={{ marginBottom: 12 }}>
                  {surgeries.map((sg, i) => (
                    <li key={i} className="chip-row">
                      <span>
                        <strong>{sg.name}</strong>
                        {sg.year && <span className="hint"> · {sg.year}</span>}
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setSurgeries((p) => p.filter((_, j) => j !== i))}
                      >
                        Remove
                      </Button>
                    </li>
                  ))}
                </ul>
              )}

              <div
                className="form-grid"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addSurgeryDraft();
                  }
                }}
              >
                <TextField
                  label="Surgery or procedure"
                  placeholder="Appendectomy, knee replacement…"
                  value={surgeryName}
                  onChange={(e) => setSurgeryName(e.target.value)}
                />
                <TextField
                  label="Year"
                  placeholder="2019"
                  inputMode="numeric"
                  value={surgeryYear}
                  onChange={(e) => setSurgeryYear(e.target.value)}
                />
              </div>
              <Button
                type="button"
                variant="ghost"
                onClick={addSurgeryDraft}
                disabled={!surgeryName.trim()}
              >
                + Add surgery
              </Button>
              <p className="hint" style={{ marginTop: 8 }}>
                Nothing to add? Leave it blank &mdash; you can add surgeries later from your profile.
              </p>
            </>
          )}

          <div className="onb__actions">
            {step > 1 && (
              <Button type="button" variant="ghost" onClick={() => setStep((s) => s - 1)}>
                Back
              </Button>
            )}
            {step < 3 ? (
              <Button
                type="button"
                onClick={() => setStep((s) => s + 1)}
                disabled={step === 1 && !name.trim()}
                fullWidth={step === 1}
              >
                Continue
              </Button>
            ) : (
              <Button type="submit" loading={saving}>
                Finish and enter Arogya
              </Button>
            )}
          </div>

          <p className="onb__skip">
            You can change any of this later from your profile.
          </p>
        </form>
      </div>
    </div>
  );
}
