import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
  api,
  type ExtractedMedication,
  type PrescriptionUploadResponse,
} from "../api/client";
import MedicineReviewCard, { SafetyFlagList } from "../components/MedicineReviewCard";
import MedicineScanner from "../components/MedicineScanner";

interface EditableMed {
  raw_name: string;
  matched_drug_id: string | null;
  dosage: string;
  frequency: string;
  duration_days: string;
  route: string;
  instructions: string;
  reminder_times: string[];
}

function toEditable(m: PrescriptionUploadResponse["extracted_medications"][number]): EditableMed {
  return {
    raw_name: m.raw_name,
    matched_drug_id: m.matched_drug_id,
    dosage: m.dosage ?? "",
    frequency: m.frequency ?? "",
    duration_days: m.duration_days ? String(m.duration_days) : "",
    route: "oral",
    instructions: m.instructions ?? "",
    reminder_times: [],
  };
}

export default function UploadPrescription() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<PrescriptionUploadResponse | null>(null);
  const [meds, setMeds] = useState<EditableMed[]>([]);
  const [doctorName, setDoctorName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [scanning, setScanning] = useState(false);

  // The review cards used to render straight off uploadResult, which is frozen
  // at the moment of upload. Anything typed in by hand afterwards was never
  // screened, and nothing on screen admitted it. These hold the LIVE result for
  // whatever is currently in the table.
  const [review, setReview] = useState<ExtractedMedication[]>([]);
  const [screening, setScreening] = useState(false);
  const [hasCritical, setHasCritical] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    setFile(f);
    setUploadResult(null);
    setError(null);
    if (f) setPreviewUrl(URL.createObjectURL(f));
  };

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await api.post<PrescriptionUploadResponse>("/prescriptions/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setUploadResult(res.data);
      setMeds(res.data.extracted_medications.map(toEditable));
      setReview(res.data.extracted_medications);
      setHasCritical(
        res.data.extracted_medications.some((m) =>
          (m.safety_flags ?? []).some((f) => f.severity === "critical")
        )
      );
      setAcknowledged(false);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Upload failed. Please try a clearer photo.");
    } finally {
      setUploading(false);
    }
  };

  // Re-screen whenever the medicine list changes. Debounced because the name
  // field re-screens on every keystroke otherwise, and a stale-response guard
  // because a slow early request must not overwrite a newer result.
  const screenSeq = useRef(0);
  const namesKey = meds.map((m) => `${m.raw_name}|${m.matched_drug_id ?? ""}`).join("~");

  useEffect(() => {
    if (!uploadResult) return;
    const rows = meds.filter((m) => m.raw_name.trim());
    if (rows.length === 0) {
      setReview([]);
      setHasCritical(false);
      return;
    }

    const seq = ++screenSeq.current;
    setScreening(true);
    const timer = setTimeout(async () => {
      try {
        const res = await api.post<{
          medications: ExtractedMedication[];
          has_critical: boolean;
        }>("/prescriptions/screen", {
          medications: rows.map((m) => ({
            raw_name: m.raw_name,
            matched_drug_id: m.matched_drug_id,
            dosage: m.dosage || null,
            frequency: m.frequency || null,
            duration_days: m.duration_days ? Number(m.duration_days) : null,
            instructions: m.instructions || null,
          })),
        });
        if (seq !== screenSeq.current) return;
        setReview(res.data.medications);
        setHasCritical(res.data.has_critical);
        // A new warning must be acknowledged again -- an acknowledgement of
        // the previous set says nothing about this one.
        setAcknowledged(false);
      } catch {
        if (seq === screenSeq.current) setReview([]);
      } finally {
        if (seq === screenSeq.current) setScreening(false);
      }
    }, 600);

    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [namesKey, uploadResult]);

  const updateMed = (idx: number, field: keyof EditableMed, value: string) => {
    setMeds((prev) => prev.map((m, i) => (i === idx ? { ...m, [field]: value } : m)));
  };

  const addReminderTime = (idx: number) => {
    setMeds((prev) =>
      prev.map((m, i) => (i === idx ? { ...m, reminder_times: [...m.reminder_times, "08:00"] } : m))
    );
  };

  const updateReminderTime = (medIdx: number, timeIdx: number, value: string) => {
    setMeds((prev) =>
      prev.map((m, i) =>
        i === medIdx
          ? { ...m, reminder_times: m.reminder_times.map((t, j) => (j === timeIdx ? value : t)) }
          : m
      )
    );
  };

  const removeReminderTime = (medIdx: number, timeIdx: number) => {
    setMeds((prev) =>
      prev.map((m, i) =>
        i === medIdx ? { ...m, reminder_times: m.reminder_times.filter((_, j) => j !== timeIdx) } : m
      )
    );
  };

  const addBlankMedication = () => {
    setMeds((prev) => [
      ...prev,
      {
        raw_name: "",
        matched_drug_id: null,
        dosage: "",
        frequency: "",
        duration_days: "",
        route: "oral",
        instructions: "",
        reminder_times: [],
      },
    ]);
  };

  const removeMedication = (idx: number) => {
    setMeds((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleConfirm = async () => {
    if (!uploadResult) return;
    const validMeds = meds.filter((m) => m.raw_name.trim());
    if (validMeds.length === 0) {
      setError("Add at least one medicine name before confirming.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.post(`/prescriptions/${uploadResult.prescription_id}/confirm`, {
        doctor_name: doctorName || null,
        medications: validMeds.map((m) => ({
          raw_name: m.raw_name,
          matched_drug_id: m.matched_drug_id,
          dosage: m.dosage || null,
          frequency: m.frequency || null,
          duration_days: m.duration_days ? Number(m.duration_days) : null,
          route: m.route || null,
          instructions: m.instructions || null,
          reminder_times: m.reminder_times,
        })),
      });
      navigate("/medications");
    } catch {
      setError("Could not save. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="upload-page">
      <h1>{t("uploadPrescription")}</h1>

      {!uploadResult && (
        <div className="upload-box">
          <p>{t("uploadCTA")}</p>
          <input type="file" accept="image/png,image/jpeg,image/webp" onChange={handleFileChange} />
          {previewUrl && <img src={previewUrl} alt="preview" className="rx-preview" />}
          <button className="btn-primary" disabled={!file || uploading} onClick={handleUpload}>
            {uploading ? t("processing") : t("chooseFile")}
          </button>
          {error && <p className="error">{error}</p>}
        </div>
      )}

      {uploadResult && (
        <div className="review-panel">
          <h2>{t("reviewTitle")}</h2>
          <p className="hint">{t("reviewHint")}</p>
          {uploadResult.is_handwritten_guess && (
            <div className="warning-banner">⚠️ {t("handwrittenWarning")}</div>
          )}
          <p className="ocr-meta">
            OCR confidence: {(uploadResult.ocr_confidence * 100).toFixed(0)}% · Status:{" "}
            {uploadResult.confirmation_status}
          </p>

          {/* Whole-prescription warnings (e.g. a banned drug spotted in the
              raw text that never matched a known medicine) sit above the
              table so they can't be missed while editing rows. */}
          {uploadResult.prescription_flags && uploadResult.prescription_flags.length > 0 && (
            <SafetyFlagList flags={uploadResult.prescription_flags} />
          )}

          <label>Doctor's name (optional)</label>
          <input value={doctorName} onChange={(e) => setDoctorName(e.target.value)} />

          <table className="meds-table">
            <thead>
              <tr>
                <th>{t("drugName")}</th>
                <th>{t("dosage")}</th>
                <th>{t("frequency")}</th>
                <th>Duration (days)</th>
                <th>{t("instructions")}</th>
                <th>Reminders</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {meds.map((m, idx) => (
                <tr key={idx}>
                  <td>
                    <input value={m.raw_name} onChange={(e) => updateMed(idx, "raw_name", e.target.value)} />
                    {m.matched_drug_id && <div className="matched-badge">✓ matched</div>}
                  </td>
                  <td>
                    <input value={m.dosage} onChange={(e) => updateMed(idx, "dosage", e.target.value)} />
                  </td>
                  <td>
                    <input value={m.frequency} onChange={(e) => updateMed(idx, "frequency", e.target.value)} />
                  </td>
                  <td>
                    <input
                      type="number"
                      value={m.duration_days}
                      onChange={(e) => updateMed(idx, "duration_days", e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      value={m.instructions}
                      onChange={(e) => updateMed(idx, "instructions", e.target.value)}
                    />
                  </td>
                  <td>
                    {m.reminder_times.map((t, tIdx) => (
                      <div key={tIdx} className="reminder-time-row">
                        <input
                          type="time"
                          value={t}
                          onChange={(e) => updateReminderTime(idx, tIdx, e.target.value)}
                        />
                        <button className="btn-link" onClick={() => removeReminderTime(idx, tIdx)}>
                          ✕
                        </button>
                      </div>
                    ))}
                    <button className="btn-link" onClick={() => addReminderTime(idx)}>
                      + {t("addReminderTime")}
                    </button>
                  </td>
                  <td>
                    <button className="btn-link" onClick={() => removeMedication(idx)}>
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="addmed-row">
            <button className="btn-secondary" onClick={addBlankMedication}>
              + Add medicine manually
            </button>
            <button className="btn-secondary" onClick={() => setScanning(true)}>
              📷 Scan a medicine pack
            </button>
          </div>

          {/* The recovery path when the prescription itself can't be read:
              photograph the box instead. Feeds straight into the same
              editable row the patient confirms. */}
          {scanning && (
            <MedicineScanner
              onClose={() => setScanning(false)}
              onUse={(r) => {
                setMeds((prev) => [
                  ...prev,
                  {
                    raw_name: r.brand_name || r.matched_generic_name || "",
                    matched_drug_id: r.matched_drug_id,
                    dosage: r.strength ?? "",
                    frequency: "",
                    duration_days: "",
                    route: r.form?.toLowerCase().includes("inject") ? "injection" : "oral",
                    instructions: "",
                    reminder_times: [],
                  },
                ]);
              }}
            />
          )}

          {/* Safety screening + price comparison for every extracted medicine,
              inline on this page so the patient sees both while still deciding
              -- not after reminders are already scheduled. */}
          {(review.length > 0 || screening) && (
            <section className="med-review-section">
              <h3 className="med-review-section__title">
                Safety check &amp; price comparison
                {screening && <span className="screening-tag"> · checking…</span>}
              </h3>
              <p className="hint">
                Every medicine in the table above is checked — the ones read from your prescription
                and the ones you add or edit yourself — against your recorded allergies, conditions,
                current medicines, and India&rsquo;s banned-medicine list. Arogya never changes a
                prescription; anything flagged here is a question for your doctor, not a reason to
                stop on your own.
              </p>
              {review.map((m, i) => (
                <MedicineReviewCard key={`${m.raw_name}-${i}`} med={m} />
              ))}
            </section>
          )}

          {error && <p className="error">{error}</p>}

          {/* A critical flag does not block saving -- the doctor may have
              prescribed it deliberately -- but it must not be scrolled past
              silently either, so saving needs one explicit tick. */}
          {hasCritical && (
            <label className="ack-row">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(e) => setAcknowledged(e.target.checked)}
              />
              <span>
                <strong>I have read the serious warnings above.</strong>
                <span className="hint" style={{ display: "block" }}>
                  Saving these medicines also schedules reminders for them. Please confirm the
                  flagged ones with your doctor or pharmacist before you start taking them.
                </span>
              </span>
            </label>
          )}

          <button
            className="btn-primary confirm-btn"
            disabled={saving || screening || (hasCritical && !acknowledged)}
            onClick={handleConfirm}
          >
            {saving ? "Saving…" : screening ? "Checking medicines…" : t("confirmAndSave")}
          </button>
        </div>
      )}
    </div>
  );
}
