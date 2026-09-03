import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { api, type UpcomingReminder } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { Badge, Button, EmptyState, Spinner } from "../components/ui";
import InsightsPanel from "../components/InsightsPanel";
import VitalsPanel from "../components/VitalsPanel";

function greetingFor(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export default function Dashboard() {
  const { t } = useTranslation();
  const { patient } = useAuth();
  const navigate = useNavigate();
  const [reminders, setReminders] = useState<UpcomingReminder[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<UpcomingReminder[]>("/reminders/upcoming")
      .then((res) => setReminders(res.data))
      .finally(() => setLoading(false));
  }, []);

  const markAdherence = async (scheduleId: string, status: string) => {
    await api.post(`/reminders/adherence/${scheduleId}`, { status });
    setReminders((prev) => prev.map((r) => (r.schedule_id === scheduleId ? { ...r, status } : r)));
  };

  const takenCount = reminders.filter((r) => r.status === "taken").length;

  return (
    <div>
      <section className="dash-hero animate-in">
        <h1>
          {greetingFor(new Date().getHours())}
          {patient?.name ? `, ${patient.name}` : ""} 👋
        </h1>
        <p>
          {loading
            ? "Checking today's schedule…"
            : reminders.length === 0
              ? "Nothing scheduled yet — add a prescription and Arogya will handle the reminders."
              : `You have ${reminders.length} dose${reminders.length === 1 ? "" : "s"} today, and you've taken ${takenCount}.`}
        </p>
      </section>

      {/* Insights before the action tiles: "how am I doing" is the question
          the dashboard exists to answer; the shortcuts are secondary. */}
      <InsightsPanel />
      <VitalsPanel />

      <div className="quick-actions">
        <Link className="action-card" to="/upload">
          📄 {t("uploadPrescription")}
        </Link>
        <Link className="action-card" to="/chat">
          💬 {t("chatbot")}
        </Link>
        <Link className="action-card" to="/prices">
          💰 {t("priceCompare")}
        </Link>
        <Link className="action-card" to="/pharmacies">
          📍 {t("pharmacies")}
        </Link>
      </div>

      <div className="section-heading">
        <h2>{t("upcomingReminders")}</h2>
        {!loading && reminders.length > 0 && (
          <Badge variant={takenCount === reminders.length ? "success" : "primary"}>
            {takenCount} of {reminders.length} taken
          </Badge>
        )}
      </div>

      {loading ? (
        <div style={{ padding: "32px", textAlign: "center" }}>
          <Spinner label="Loading today's reminders…" />
        </div>
      ) : reminders.length === 0 ? (
        <EmptyState
          icon="💊"
          title="No reminders scheduled yet"
          description="Upload a prescription and Arogya will build your daily schedule automatically."
          action={<Button onClick={() => navigate("/upload")}>Upload a prescription</Button>}
        />
      ) : (
        <ul className="reminder-list">
          {reminders.map((r) => (
            <li key={r.schedule_id} className={`reminder-item status-${r.status}`}>
              <div className="reminder-main">
                <strong>{r.time_of_day}</strong> — {r.drug_name} {r.dosage && `(${r.dosage})`}
                {r.instructions && <div className="reminder-instructions">{r.instructions}</div>}
                {r.storage_note && (
                  <div className="storage-note">
                    ❄️ {t("storageNote")}: {r.storage_note}
                  </div>
                )}
              </div>
              <div className="reminder-actions">
                <Button
                  size="sm"
                  variant={r.status === "taken" ? "primary" : "secondary"}
                  onClick={() => markAdherence(r.schedule_id, "taken")}
                >
                  {t("markTaken")}
                </Button>
                <Button
                  size="sm"
                  variant={r.status === "skipped" ? "primary" : "secondary"}
                  onClick={() => markAdherence(r.schedule_id, "skipped")}
                >
                  {t("markSkipped")}
                </Button>
                <Button
                  size="sm"
                  variant={r.status === "snoozed" ? "primary" : "secondary"}
                  onClick={() => markAdherence(r.schedule_id, "snoozed")}
                >
                  {t("markSnoozed")}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
