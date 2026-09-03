import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { Badge, Button, Card, EmptyState, Spinner } from "../components/ui";

interface MedicationOut {
  id: string;
  raw_name: string;
  matched_drug_id: string | null;
  matched_generic_name: string | null;
  dosage: string | null;
  frequency: string | null;
  duration_days: number | null;
  route: string | null;
  instructions: string | null;
  is_confirmed: boolean;
  reminder_times: string[];
  storage_note: string | null;
  drug_class: string | null;
}

interface PrescriptionOut {
  id: string;
  uploaded_at: string;
  doctor_name: string | null;
  confirmation_status: string;
  ocr_confidence: number | null;
  is_handwritten_guess: boolean;
  medications: MedicationOut[];
}

function MedicineRow({ m }: { m: MedicationOut }) {
  const title = m.matched_generic_name || m.raw_name;
  const alias =
    m.matched_generic_name && m.raw_name.toLowerCase() !== m.matched_generic_name.toLowerCase()
      ? m.raw_name
      : null;

  return (
    <li className="med-item">
      <div className="med-item__main">
        <div className="med-item__head">
          <span className="med-item__name">{title}</span>
          {m.dosage && <span className="med-item__dose">{m.dosage}</span>}
          {m.drug_class && <Badge variant="neutral">{m.drug_class}</Badge>}
        </div>

        {alias && <p className="med-item__alias">Written on the prescription as “{alias}”</p>}

        {/* Explicit label/value pairs rather than bare table cells: a blank
            column reads as broken, whereas "Duration — not specified" reads
            as information. */}
        <dl className="med-item__facts">
          <div>
            <dt>How often</dt>
            <dd>{m.frequency || "Not specified"}</dd>
          </div>
          <div>
            <dt>Duration</dt>
            <dd>{m.duration_days ? `${m.duration_days} days` : "Not specified"}</dd>
          </div>
          <div>
            <dt>Route</dt>
            <dd>{m.route || "Not specified"}</dd>
          </div>
          <div>
            <dt>Reminders</dt>
            <dd>
              {m.reminder_times.length > 0 ? (
                m.reminder_times.map((t) => (
                  <span key={t} className="med-item__time">
                    {t}
                  </span>
                ))
              ) : (
                <span className="med-item__muted">None set</span>
              )}
            </dd>
          </div>
        </dl>

        {m.instructions && <p className="med-item__instructions">📋 {m.instructions}</p>}
        {m.storage_note && <p className="med-item__storage">❄️ Storage: {m.storage_note}</p>}
      </div>
    </li>
  );
}

export default function Medications() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [prescriptions, setPrescriptions] = useState<PrescriptionOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = () =>
    api
      .get<PrescriptionOut[]>("/prescriptions")
      .then((res) => setPrescriptions(res.data))
      .finally(() => setLoading(false));

  useEffect(() => {
    load();
  }, []);

  const discard = async (id: string) => {
    if (!window.confirm("Discard this unconfirmed scan? The uploaded image will be removed.")) return;
    setBusyId(id);
    try {
      await api.delete(`/prescriptions/${id}`);
      setPrescriptions((prev) => prev.filter((p) => p.id !== id));
    } finally {
      setBusyId(null);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: "center" }}>
        <Spinner size="lg" label="Loading your medicines…" />
      </div>
    );
  }

  // Split by whether the patient actually confirmed the scan. Mixing the two
  // was the bug: an abandoned upload rendered as an empty table that looked
  // like the app had lost the data.
  const confirmed = prescriptions.filter((p) => p.medications.length > 0);
  const pending = prescriptions.filter((p) => p.medications.length === 0);
  const totalMeds = confirmed.reduce((n, p) => n + p.medications.length, 0);

  return (
    <div>
      <div className="dash-hero animate-in">
        <h1>{t("myMedications")}</h1>
        <p>
          {totalMeds > 0
            ? `${totalMeds} confirmed medicine${totalMeds === 1 ? "" : "s"} across ${confirmed.length} prescription${confirmed.length === 1 ? "" : "s"}.`
            : "Nothing confirmed yet — upload a prescription and confirm it to start tracking."}
        </p>
      </div>

      {confirmed.length === 0 && pending.length === 0 && (
        <EmptyState
          icon="💊"
          title="No prescriptions yet"
          description="Upload a photo of a prescription and Arogya will extract the medicines for you to confirm."
          action={<Button onClick={() => navigate("/upload")}>Upload prescription</Button>}
        />
      )}

      {confirmed.map((p) => (
        <Card key={p.id} className="stack-card">
          <div className="prescription-header">
            <strong>{new Date(p.uploaded_at).toLocaleDateString()}</strong>
            {p.doctor_name && <span> — {p.doctor_name}</span>}
            <Badge variant="success">confirmed</Badge>
          </div>
          <ul className="med-list">
            {p.medications.map((m) => (
              <MedicineRow key={m.id} m={m} />
            ))}
          </ul>
        </Card>
      ))}

      {pending.length > 0 && (
        <section style={{ marginTop: "var(--space-xl)" }}>
          <div className="section-heading">
            <h2>Scans waiting for you</h2>
            <Badge variant="warning">{pending.length} not confirmed</Badge>
          </div>
          <p className="hint">
            These were scanned but never confirmed, so no medicines were saved and no reminders are
            running for them. Upload the prescription again to review it, or discard the scan.
          </p>
          {pending.map((p) => (
            <Card key={p.id} className="stack-card">
              <div className="prescription-header">
                <strong>{new Date(p.uploaded_at).toLocaleDateString()}</strong>
                <Badge variant="warning">{p.confirmation_status.replace(/_/g, " ")}</Badge>
                {p.ocr_confidence !== null && (
                  <span className="hint"> · scan quality {(p.ocr_confidence * 100).toFixed(0)}%</span>
                )}
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                <Button size="sm" onClick={() => navigate("/upload")}>
                  Upload again to review
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  loading={busyId === p.id}
                  onClick={() => discard(p.id)}
                >
                  Discard scan
                </Button>
              </div>
            </Card>
          ))}
        </section>
      )}
    </div>
  );
}
