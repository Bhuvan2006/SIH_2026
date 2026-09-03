import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  type Appointment,
  type DaySlots,
  type DoctorPatientSummary,
} from "../api/client";
import { Badge, Button, Card, EmptyState, Modal, Spinner } from "../components/ui";

const STATUS_VARIANT: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  confirmed: "success",
  pending: "warning",
  cancelled: "danger",
  completed: "neutral",
};

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")}`;
}

function shiftDate(iso: string, days: number) {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")}`;
}

function prettyDate(iso: string) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
}

export default function DoctorAppointments() {
  const [date, setDate] = useState(todayISO);
  const [dayList, setDayList] = useState<Appointment[]>([]);
  const [upcoming, setUpcoming] = useState<Appointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Follow-up scheduling
  const [scheduling, setScheduling] = useState(false);
  const [patients, setPatients] = useState<DoctorPatientSummary[]>([]);
  const [newPatientId, setNewPatientId] = useState("");
  const [newDate, setNewDate] = useState(todayISO);
  const [newSlots, setNewSlots] = useState<DaySlots | null>(null);
  const [newSlot, setNewSlot] = useState("");
  const [newNotes, setNewNotes] = useState("");
  const [saving, setSaving] = useState(false);

  // Consultation notes
  const [notesFor, setNotesFor] = useState<Appointment | null>(null);
  const [noteDraft, setNoteDraft] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.get<Appointment[]>("/doctor/appointments", { params: { date } }),
      api.get<Appointment[]>("/doctor/appointments", { params: { upcoming: true } }),
    ])
      .then(([d, u]) => {
        setDayList(d.data);
        setUpcoming(u.data);
      })
      .catch(() => setError("Could not load your diary."))
      .finally(() => setLoading(false));
  }, [date]);

  useEffect(load, [load]);

  useEffect(() => {
    if (!scheduling) return;
    api
      .get<DoctorPatientSummary[]>("/doctor/patients")
      .then((res) => setPatients(res.data))
      .catch(() => setPatients([]));
  }, [scheduling]);

  useEffect(() => {
    if (!scheduling || !newDate) return;
    setNewSlot("");
    api
      .get<DaySlots>("/doctor/slots", { params: { date: newDate } })
      .then((res) => setNewSlots(res.data))
      .catch(() => setNewSlots(null));
  }, [scheduling, newDate]);

  const setStatus = async (a: Appointment, status: string) => {
    setError(null);
    try {
      await api.patch(`/doctor/appointments/${a.id}`, { status });
      load();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Could not update that appointment.");
    }
  };

  const saveNotes = async () => {
    if (!notesFor) return;
    try {
      await api.patch(`/doctor/appointments/${notesFor.id}`, { doctor_notes: noteDraft });
      setNotesFor(null);
      load();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Could not save those notes.");
    }
  };

  const scheduleFollowUp = async () => {
    if (!newPatientId || !newSlot) {
      setError("Pick a patient and a time.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.post("/doctor/appointments", {
        patient_id: newPatientId,
        date: newDate,
        time_slot: newSlot,
        notes: newNotes.trim() || null,
      });
      setScheduling(false);
      setNewSlot("");
      setNewNotes("");
      setNewPatientId("");
      load();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Could not schedule that appointment.");
    } finally {
      setSaving(false);
    }
  };

  const row = (a: Appointment) => (
    <Card key={a.id} className="appt-card">
      <div className="appt-card__head">
        <div>
          <p className="appt-card__when">
            <strong>{a.time_slot_label ?? a.time_slot}</strong> · {prettyDate(a.date)}
          </p>
          <p className="appt-card__who">
            {a.patient?.id ? (
              <Link to={`/doctor/patient/${a.patient.id}`}>{a.patient?.name ?? "Patient"}</Link>
            ) : (
              (a.patient?.name ?? "Patient")
            )}
            {a.patient?.is_pregnant ? " · pregnant" : ""}
          </p>
        </div>
        <Badge variant={STATUS_VARIANT[a.status] ?? "neutral"}>{a.status}</Badge>
      </div>

      {a.notes && <p className="appt-card__notes">Reason: {a.notes}</p>}
      {a.doctor_notes && (
        <p className="appt-card__doctornotes">
          <strong>Your note:</strong> {a.doctor_notes}
        </p>
      )}
      {a.created_by === "doctor" && <p className="appt-card__meta">You scheduled this.</p>}

      <div className="appt-card__actions">
        {a.status === "pending" && (
          <>
            <Button onClick={() => setStatus(a, "confirmed")}>Confirm</Button>
            <Button variant="secondary" onClick={() => setStatus(a, "cancelled")}>
              Decline
            </Button>
          </>
        )}
        {a.status === "confirmed" && (
          <>
            <Button onClick={() => setStatus(a, "completed")}>Mark seen</Button>
            <Button variant="secondary" onClick={() => setStatus(a, "cancelled")}>
              Cancel
            </Button>
          </>
        )}
        {(a.status === "confirmed" || a.status === "completed") && (
          <Button
            variant="link"
            onClick={() => {
              setNotesFor(a);
              setNoteDraft(a.doctor_notes ?? "");
            }}
          >
            {a.doctor_notes ? "Edit note" : "Add note"}
          </Button>
        )}
      </div>
    </Card>
  );

  return (
    <div className="doctor-appointments">
      <div className="wsection__head">
        <h1>Appointments</h1>
        <Button onClick={() => setScheduling(true)}>+ Schedule a follow-up</Button>
      </div>

      {error && <p className="error" role="alert">{error}</p>}

      <section className="wsection">
        <div className="daynav">
          <Button variant="secondary" onClick={() => setDate(shiftDate(date, -1))}>
            ← Previous
          </Button>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <Button variant="secondary" onClick={() => setDate(shiftDate(date, 1))}>
            Next →
          </Button>
          <Button variant="link" onClick={() => setDate(todayISO())}>
            Today
          </Button>
        </div>

        <h2 className="wsection__title">{prettyDate(date)}</h2>
        {loading ? (
          <Spinner label="Loading…" />
        ) : dayList.length === 0 ? (
          <EmptyState
            icon="📋"
            title="Nothing booked this day"
            description="Patients who book this date will appear here."
          />
        ) : (
          <div className="appt-list">{dayList.map(row)}</div>
        )}
      </section>

      <section className="wsection">
        <h2 className="wsection__title">All upcoming ({upcoming.length})</h2>
        {upcoming.length === 0 ? (
          <p className="hint">No upcoming appointments.</p>
        ) : (
          <div className="appt-list">{upcoming.map(row)}</div>
        )}
      </section>

      {scheduling && (
        <Modal isOpen title="Schedule a follow-up" onClose={() => setScheduling(false)}>
          <div className="book-form">
            <label htmlFor="fu-patient">Patient</label>
            <select
              id="fu-patient"
              value={newPatientId}
              onChange={(e) => setNewPatientId(e.target.value)}
            >
              <option value="">Choose a patient…</option>
              {patients.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name ?? p.phone}
                </option>
              ))}
            </select>
            <p className="hint">
              Only patients who have booked with you before. That relationship is what gives you
              access to their record.
            </p>

            <label htmlFor="fu-date">Date</label>
            <input
              id="fu-date"
              type="date"
              value={newDate}
              min={todayISO()}
              onChange={(e) => setNewDate(e.target.value)}
            />

            <label>Time</label>
            {newSlots?.closed_reason ? (
              <p className="hint">{newSlots.closed_reason}</p>
            ) : newSlots && newSlots.slots.length > 0 ? (
              <div className="slot-grid" role="group" aria-label="Available times">
                {newSlots.slots.map((s) => (
                  <button
                    key={s.time_slot}
                    type="button"
                    className={`slot ${newSlot === s.time_slot ? "slot--on" : ""} ${
                      s.available ? "" : "slot--off"
                    }`}
                    disabled={!s.available}
                    title={s.reason ?? undefined}
                    onClick={() => setNewSlot(s.time_slot)}
                  >
                    {s.time_slot}
                  </button>
                ))}
              </div>
            ) : (
              <p className="hint">No slots on this date.</p>
            )}

            <label htmlFor="fu-notes">Reason (optional)</label>
            <input
              id="fu-notes"
              value={newNotes}
              placeholder="e.g. 32-week growth scan"
              onChange={(e) => setNewNotes(e.target.value)}
            />

            <Button onClick={scheduleFollowUp} disabled={saving || !newSlot}>
              {saving ? "Scheduling…" : "Schedule"}
            </Button>
            <p className="hint">
              Follow-ups you schedule are confirmed straight away — the patient just sees it in
              their list.
            </p>
          </div>
        </Modal>
      )}

      {notesFor && (
        <Modal isOpen title="Consultation note" onClose={() => setNotesFor(null)}>
          <div className="book-form">
            <p className="hint">
              {notesFor.patient?.name} · {prettyDate(notesFor.date)}{" "}
              {notesFor.time_slot_label}
            </p>
            <textarea
              rows={6}
              value={noteDraft}
              onChange={(e) => setNoteDraft(e.target.value)}
              placeholder="What you observed, what you advised…"
            />
            <p className="hint">The patient can read this in their appointment list.</p>
            <Button onClick={saveNotes}>Save note</Button>
          </div>
        </Modal>
      )}
    </div>
  );
}
