import { useEffect, useState } from "react";
import { api, type Doctor } from "../api/client";
import { Button, Card, Spinner } from "../components/ui";

/**
 * The doctor's own details.
 *
 * Name and specialisation are not decoration: a doctor without them is hidden
 * from the patient booking list entirely, because a picker row reading "null"
 * is not something a patient can choose.
 */
export default function DoctorProfile() {
  const [doctor, setDoctor] = useState<Doctor | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const [form, setForm] = useState({
    name: "",
    specialization: "",
    license_no: "",
    clinic_name: "",
    clinic_address: "",
    consultation_fee_inr: "",
    languages: "",
  });

  useEffect(() => {
    api
      .get<Doctor>("/doctor/me")
      .then((res) => {
        setDoctor(res.data);
        setForm({
          name: res.data.name ?? "",
          specialization: res.data.specialization ?? "",
          license_no: res.data.license_no ?? "",
          clinic_name: res.data.clinic_name ?? "",
          clinic_address: res.data.clinic_address ?? "",
          consultation_fee_inr:
            res.data.consultation_fee_inr != null ? String(res.data.consultation_fee_inr) : "",
          languages: res.data.languages ?? "",
        });
      })
      .catch(() => setError("Could not load your profile."))
      .finally(() => setLoading(false));
  }, []);

  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  const save = async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const res = await api.patch<Doctor>("/doctor/me", {
        ...form,
        consultation_fee_inr: form.consultation_fee_inr
          ? Number(form.consultation_fee_inr)
          : null,
      });
      setDoctor(res.data);
      setSaved(true);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Could not save your profile.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Spinner label="Loading your profile…" />;

  return (
    <div className="doctor-profile">
      <h1>My profile</h1>

      {error && <p className="error" role="alert">{error}</p>}
      {saved && <p className="success-note" role="status">Profile saved.</p>}

      {doctor && !doctor.profile_completed && (
        <Card className="warn-card">
          <p>
            <strong>Patients can't find you yet.</strong> Add your name and specialisation to
            appear in the booking list.
          </p>
        </Card>
      )}

      <Card className="book-form">
        <label htmlFor="dp-name">Name *</label>
        <input id="dp-name" value={form.name} onChange={set("name")} placeholder="Dr. Meera Iyer" />

        <label htmlFor="dp-spec">Specialisation *</label>
        <input
          id="dp-spec"
          value={form.specialization}
          onChange={set("specialization")}
          placeholder="Obstetrics & Gynaecology"
        />

        <label htmlFor="dp-lic">Medical council registration</label>
        <input id="dp-lic" value={form.license_no} onChange={set("license_no")} placeholder="KMC-48221" />

        <label htmlFor="dp-clinic">Clinic or hospital</label>
        <input id="dp-clinic" value={form.clinic_name} onChange={set("clinic_name")} />

        <label htmlFor="dp-addr">Address</label>
        <input id="dp-addr" value={form.clinic_address} onChange={set("clinic_address")} />

        <label htmlFor="dp-fee">Consultation fee (₹)</label>
        <input
          id="dp-fee"
          type="number"
          min="0"
          value={form.consultation_fee_inr}
          onChange={set("consultation_fee_inr")}
        />

        <label htmlFor="dp-lang">Languages you consult in</label>
        <input
          id="dp-lang"
          value={form.languages}
          onChange={set("languages")}
          placeholder="English, Hindi, Kannada"
        />

        <Button onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save profile"}
        </Button>
        <p className="hint">
          Phone: {doctor?.phone}. Arogya does not verify medical registration — this is a
          prototype, and a real deployment must check the council register before a doctor can
          see patient records.
        </p>
      </Card>
    </div>
  );
}
