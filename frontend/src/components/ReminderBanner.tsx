import { useCallback, useEffect, useRef, useState } from "react";
import { api, type DueReminder } from "../api/client";
import { Button, Modal } from "./ui";

const POLL_MS = 60_000;

/**
 * Persistent "dose is due" banner.
 *
 * The backend notifier writes to a log (mock) or sends an SMS (msg91) — neither
 * of which a patient sitting in the app ever sees. This polls /reminders/due so
 * an overdue dose is actually visible in-app, and mirrors it to a native
 * browser notification when the user has granted permission.
 */
export default function ReminderBanner() {
  const [due, setDue] = useState<DueReminder[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const notifiedRef = useRef<Set<string>>(new Set());

  // A dose that just came due gets an interrupting modal, not only the banner.
  // The banner is easy to scroll past; the whole point of a reminder is that
  // it interrupts. Dismissing the modal leaves the banner as the quiet
  // fallback, and each dose only ever pops once.
  const [popup, setPopup] = useState<DueReminder | null>(null);
  const poppedRef = useRef<Set<string>>(new Set());

  const fetchDue = useCallback(async () => {
    try {
      const res = await api.get<DueReminder[]>("/reminders/due");
      setDue(res.data);

      // Pop the most overdue dose we haven't already shown.
      const unseen = res.data.find((d) => !poppedRef.current.has(d.adherence_log_id));
      if (unseen) {
        poppedRef.current.add(unseen.adherence_log_id);
        setPopup(unseen);
      }

      // Fire a native notification once per dose, only if the user opted in.
      if ("Notification" in window && Notification.permission === "granted") {
        for (const d of res.data) {
          if (notifiedRef.current.has(d.adherence_log_id)) continue;
          notifiedRef.current.add(d.adherence_log_id);
          new Notification("Time for your medicine", {
            body: `${d.drug_name}${d.dosage ? ` (${d.dosage})` : ""} — due ${d.time_of_day}`,
            tag: d.adherence_log_id,
          });
        }
      }
    } catch {
      // Silent: a failed poll shouldn't surface an error banner over the app.
    }
  }, []);

  useEffect(() => {
    fetchDue();
    const id = setInterval(fetchDue, POLL_MS);
    return () => clearInterval(id);
  }, [fetchDue]);

  const act = async (scheduleId: string, status: string) => {
    setBusyId(scheduleId);
    try {
      await api.post(`/reminders/adherence/${scheduleId}`, { status });
      setDue((prev) => prev.filter((d) => d.schedule_id !== scheduleId));
      setPopup((p) => (p && p.schedule_id === scheduleId ? null : p));
    } finally {
      setBusyId(null);
    }
  };

  const popupModal = popup && (
    <Modal
      isOpen
      onClose={() => setPopup(null)}
      title="Time for your medicine"
      footer={
        <>
          <Button
            variant="ghost"
            disabled={busyId === popup.schedule_id}
            onClick={() => act(popup.schedule_id, "snoozed")}
          >
            Snooze
          </Button>
          <Button
            variant="ghost"
            disabled={busyId === popup.schedule_id}
            onClick={() => act(popup.schedule_id, "skipped")}
          >
            Skip
          </Button>
          <Button
            loading={busyId === popup.schedule_id}
            onClick={() => act(popup.schedule_id, "taken")}
          >
            I&rsquo;ve taken it
          </Button>
        </>
      }
    >
      <div className="dosepop">
        <span className="dosepop__pill" aria-hidden="true">💊</span>
        <div>
          <p className="dosepop__name">
            {popup.drug_name}
            {popup.dosage && <span className="dosepop__dose"> {popup.dosage}</span>}
          </p>
          <p className="dosepop__when">
            Due at {popup.time_of_day}
            {popup.minutes_late > 0 && ` · ${popup.minutes_late} min ago`}
          </p>
          {popup.instructions && <p className="dosepop__instr">📋 {popup.instructions}</p>}
        </div>
      </div>
    </Modal>
  );

  if (due.length === 0) return popupModal ?? null;

  const first = due[0];

  return (
    <>
      {popupModal}
    <div className="reminder-banner" role="status" aria-live="polite">
      <div className="reminder-banner__icon" aria-hidden="true">
        💊
      </div>
      <div className="reminder-banner__body">
        <p className="reminder-banner__title">
          Time to take {first.drug_name}
          {first.dosage ? ` (${first.dosage})` : ""}
        </p>
        <p className="reminder-banner__meta">
          Due at {first.time_of_day}
          {first.minutes_late > 0 && ` · ${first.minutes_late} min ago`}
          {due.length > 1 && ` · +${due.length - 1} more due`}
        </p>
        {first.instructions && <p className="reminder-banner__meta">{first.instructions}</p>}
      </div>
      <div className="reminder-banner__actions">
        <Button
          size="sm"
          loading={busyId === first.schedule_id}
          onClick={() => act(first.schedule_id, "taken")}
        >
          Taken
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={busyId === first.schedule_id}
          onClick={() => act(first.schedule_id, "snoozed")}
        >
          Snooze
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={busyId === first.schedule_id}
          onClick={() => act(first.schedule_id, "skipped")}
        >
          Skip
        </Button>
      </div>
    </div>
    </>
  );
}
