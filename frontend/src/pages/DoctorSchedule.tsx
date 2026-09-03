import { useCallback, useEffect, useState } from "react";
import { api, type Availability, type TimeOff } from "../api/client";
import { Badge, Button, Card, EmptyState, Spinner } from "../components/ui";

const WEEKDAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")}`;
}

function prettyDate(iso: string) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function countSlots(a: Availability) {
  const [sh, sm] = a.start_time.split(":").map(Number);
  const [eh, em] = a.end_time.split(":").map(Number);
  const minutes = eh * 60 + em - (sh * 60 + sm);
  return minutes > 0 ? Math.floor(minutes / a.slot_minutes) : 0;
}

/**
 * Where a doctor says when they actually sit.
 *
 * Before this, bookable slots were a hardcoded list — the same twelve times
 * for every doctor, every day of the week, including days they don't hold
 * clinic. A patient could book Sunday evening with a doctor who only works
 * weekday mornings, and the doctor had no way to say otherwise.
 */
export default function DoctorSchedule() {
  const [sessions, setSessions] = useState<Availability[]>([]);
  const [timeOff, setTimeOff] = useState<TimeOff[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [weekday, setWeekday] = useState(0);
  const [startTime, setStartTime] = useState("09:00");
  const [endTime, setEndTime] = useState("13:00");
  const [slotMinutes, setSlotMinutes] = useState(30);

  const [offDate, setOffDate] = useState(todayISO);
  const [offReason, setOffReason] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.get<Availability[]>("/doctor/availability"),
      api.get<TimeOff[]>("/doctor/time-off"),
    ])
      .then(([a, t]) => {
        setSessions(a.data);
        setTimeOff(t.data);
      })
      .catch(() => setError("Could not load your schedule."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const addSession = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.post("/doctor/availability", {
        weekday,
        start_time: startTime,
        end_time: endTime,
        slot_minutes: slotMinutes,
        active: true,
      });
      load();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Could not add that session.");
    } finally {
      setSaving(false);
    }
  };

  const removeSession = async (id: string) => {
    setError(null);
    try {
      await api.delete(`/doctor/availability/${id}`);
      load();
    } catch {
      setError("Could not remove that session.");
    }
  };

  const addTimeOff = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.post("/doctor/time-off", {
        date: offDate,
        reason: offReason.trim() || null,
      });
      setOffReason("");
      load();
    } catch (err: any) {
      // The API refuses to block a day that already has patients booked, and
      // says how many. Surfacing that is the whole point.
      setError(err?.response?.data?.detail ?? "Could not block that date.");
    } finally {
      setSaving(false);
    }
  };

  const removeTimeOff = async (id: string) => {
    try {
      await api.delete(`/doctor/time-off/${id}`);
      load();
    } catch {
      setError("Could not unblock that date.");
    }
  };

  if (loading) return <Spinner label="Loading your schedule…" />;

  const byDay = WEEKDAYS.map((name, index) => ({
    name,
    index,
    rows: sessions.filter((s) => s.weekday === index),
  }));

  return (
    <div className="doctor-schedule">
      <h1>My schedule</h1>
      <p className="hint">
        Patients can only book the times you set here. Changing your hours does not move
        appointments already in your diary.
      </p>

      {error && <p className="error" role="alert">{error}</p>}

      <section className="wsection">
        <h2 className="wsection__title">Clinic hours</h2>
        <div className="week-grid">
          {byDay.map((day) => (
            <Card key={day.index} className="daycard">
              <div className="daycard__head">
                <strong>{day.name}</strong>
                {day.rows.length === 0 && <Badge variant="neutral">Closed</Badge>}
              </div>
              {day.rows.length === 0 ? (
                <p className="hint">No clinic.</p>
              ) : (
                <ul className="session-list">
                  {day.rows.map((s) => (
                    <li key={s.id}>
                      <span>
                        {s.start_time}–{s.end_time}
                        <span className="hint"> · {countSlots(s)} slots of {s.slot_minutes}min</span>
                      </span>
                      <Button variant="link" onClick={() => removeSession(s.id)}>
                        Remove
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          ))}
        </div>

        <Card className="book-form" title="Add a session">
          <label htmlFor="sched-day">Day</label>
          <select
            id="sched-day"
            value={weekday}
            onChange={(e) => setWeekday(Number(e.target.value))}
          >
            {WEEKDAYS.map((d, i) => (
              <option key={d} value={i}>
                {d}
              </option>
            ))}
          </select>

          <label htmlFor="sched-start">Starts</label>
          <input
            id="sched-start"
            type="time"
            value={startTime}
            onChange={(e) => setStartTime(e.target.value)}
          />

          <label htmlFor="sched-end">Ends</label>
          <input
            id="sched-end"
            type="time"
            value={endTime}
            onChange={(e) => setEndTime(e.target.value)}
          />

          <label htmlFor="sched-len">Minutes per patient</label>
          <select
            id="sched-len"
            value={slotMinutes}
            onChange={(e) => setSlotMinutes(Number(e.target.value))}
          >
            {[10, 15, 20, 30, 45, 60].map((m) => (
              <option key={m} value={m}>
                {m} minutes
              </option>
            ))}
          </select>

          <Button onClick={addSession} disabled={saving}>
            {saving ? "Saving…" : "Add session"}
          </Button>
          <p className="hint">
            Add two sessions for a day to run a morning and an evening OPD with a gap between.
          </p>
        </Card>
      </section>

      <section className="wsection">
        <h2 className="wsection__title">Days off</h2>
        {timeOff.length === 0 ? (
          <EmptyState
            icon="🗓️"
            title="No blocked dates"
            description="Block a date for leave or a holiday and patients won't be offered it."
          />
        ) : (
          <ul className="session-list">
            {timeOff.map((t) => (
              <li key={t.id}>
                <span>
                  <strong>{prettyDate(t.date)}</strong>
                  {t.reason ? <span className="hint"> · {t.reason}</span> : null}
                </span>
                <Button variant="link" onClick={() => removeTimeOff(t.id)}>
                  Unblock
                </Button>
              </li>
            ))}
          </ul>
        )}

        <Card className="book-form" title="Block a date">
          <label htmlFor="off-date">Date</label>
          <input
            id="off-date"
            type="date"
            min={todayISO()}
            value={offDate}
            onChange={(e) => setOffDate(e.target.value)}
          />
          <label htmlFor="off-reason">Reason (optional)</label>
          <input
            id="off-reason"
            value={offReason}
            placeholder="e.g. Conference"
            onChange={(e) => setOffReason(e.target.value)}
          />
          <Button onClick={addTimeOff} disabled={saving}>
            {saving ? "Saving…" : "Block this date"}
          </Button>
        </Card>
      </section>
    </div>
  );
}
