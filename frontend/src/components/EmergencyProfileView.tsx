import type { EmergencyProfile } from "../api/client";

function ageFrom(dob: string | null): string | null {
  if (!dob) return null;
  const d = new Date(dob);
  if (Number.isNaN(d.getTime())) return null;
  const diff = Date.now() - d.getTime();
  const years = Math.floor(diff / (365.25 * 24 * 3600 * 1000));
  return years > 0 && years < 130 ? `${years} yrs` : null;
}

/**
 * The emergency profile as a first responder reads it.
 *
 * Ordering is deliberate and clinical, not cosmetic: red-flag alerts first
 * (they change treatment in the first seconds), then blood group and
 * allergies, then who to call, then the fuller record. Someone scanning this
 * at a roadside is triaging in seconds, so the life-critical facts must be
 * legible without scrolling.
 */
export default function EmergencyProfileView({ profile }: { profile: EmergencyProfile }) {
  const age = ageFrom(profile.date_of_birth);

  return (
    <div className="emg">
      <header className="emg__header">
        <div>
          <p className="emg__eyebrow">Emergency medical information</p>
          <h1 className="emg__name">{profile.name || "Name not provided"}</h1>
          <p className="emg__sub">
            {[age, profile.gender, profile.date_of_birth].filter(Boolean).join(" · ")}
          </p>
        </div>
        <div className="emg__blood">
          <span className="emg__blood-label">Blood</span>
          <span className="emg__blood-value">{profile.blood_group || "—"}</span>
        </div>
      </header>

      {profile.critical_alerts.length > 0 && (
        <section className="emg__alerts" role="alert">
          <h2 className="emg__alerts-title">⚠️ Critical alerts</h2>
          <ul>
            {profile.critical_alerts.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </section>
      )}

      <div className="emg__grid">
        <section className="emg__block">
          <h2 className="emg__block-title">Allergies</h2>
          {profile.allergies.length === 0 ? (
            <p className="emg__none">None recorded</p>
          ) : (
            <ul className="emg__list">
              {profile.allergies.map((a, i) => (
                <li key={i}>
                  <strong>{a.allergen}</strong>
                  <span
                    className={`emg__sev emg__sev--${
                      a.severity === "anaphylaxis" || a.severity === "severe" ? "high" : "low"
                    }`}
                  >
                    {a.severity}
                  </span>
                  {a.reaction && <div className="emg__muted">{a.reaction}</div>}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="emg__block">
          <h2 className="emg__block-title">Emergency contacts</h2>
          {profile.emergency_contacts.length === 0 ? (
            <p className="emg__none">None recorded</p>
          ) : (
            <ul className="emg__list">
              {profile.emergency_contacts.map((c, i) => (
                <li key={i}>
                  <strong>{c.name}</strong>
                  {c.relationship && <span className="emg__muted"> · {c.relationship}</span>}
                  <div>
                    <a className="emg__tel" href={`tel:${c.phone}`}>
                      📞 {c.phone}
                    </a>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="emg__block">
          <h2 className="emg__block-title">Conditions</h2>
          {profile.conditions.length === 0 ? (
            <p className="emg__none">None recorded</p>
          ) : (
            <ul className="emg__list">
              {profile.conditions.map((c, i) => (
                <li key={i}>
                  {/* Name is the clinical fact and always leads; notes are
                      supporting detail, never a replacement for it. */}
                  <strong style={{ textTransform: "capitalize" }}>
                    {c.name.replace(/_/g, " ")}
                  </strong>
                  {c.notes && <div className="emg__muted">{c.notes}</div>}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="emg__block">
          <h2 className="emg__block-title">Current medicines</h2>
          {profile.medications.length === 0 ? (
            <p className="emg__none">None recorded</p>
          ) : (
            <ul className="emg__list">
              {profile.medications.map((m, i) => (
                <li key={i}>
                  <strong>{m.name}</strong>
                  <span className="emg__muted">
                    {" "}
                    {[m.dosage, m.frequency].filter(Boolean).join(" · ")}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {(profile.implants_devices || profile.emergency_notes || profile.organ_donor) && (
        <section className="emg__block">
          <h2 className="emg__block-title">Other important details</h2>
          <ul className="emg__list">
            {profile.implants_devices && (
              <li>
                <strong>Implants / devices:</strong> {profile.implants_devices}
              </li>
            )}
            {profile.organ_donor && (
              <li>
                <strong>Registered organ donor</strong>
              </li>
            )}
            {profile.emergency_notes && <li>{profile.emergency_notes}</li>}
          </ul>
        </section>
      )}

      <div className="emg__grid">
        <section className="emg__block">
          <h2 className="emg__block-title">Doctor</h2>
          {profile.primary_doctor.name || profile.primary_doctor.phone ? (
            <p className="emg__list">
              {profile.primary_doctor.name}
              {profile.primary_doctor.phone && (
                <>
                  <br />
                  <a className="emg__tel" href={`tel:${profile.primary_doctor.phone}`}>
                    📞 {profile.primary_doctor.phone}
                  </a>
                </>
              )}
            </p>
          ) : (
            <p className="emg__none">Not recorded</p>
          )}
        </section>

        <section className="emg__block">
          <h2 className="emg__block-title">Insurance</h2>
          {profile.insurance.provider || profile.insurance.policy_no ? (
            <p className="emg__list">
              {profile.insurance.provider}
              {profile.insurance.policy_no && (
                <>
                  <br />
                  Policy: {profile.insurance.policy_no}
                </>
              )}
            </p>
          ) : (
            <p className="emg__none">Not recorded</p>
          )}
        </section>
      </div>

      <footer className="emg__footer">
        Patient-entered information shared via Arogya. Verify clinically where time allows — it is
        not a substitute for medical assessment.
      </footer>
    </div>
  );
}
