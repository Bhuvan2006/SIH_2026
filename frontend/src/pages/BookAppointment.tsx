import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type Appointment,
  type DaySlots,
  type Doctor,
} from "../api/client";
import { Badge, Button, Card, EmptyState, Spinner } from "../components/ui";

const STATUS_VARIANT: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  confirmed: "success",
  pending: "warning",
  cancelled: "danger",
  completed: "neutral",
};

const STATUS_LABEL: Record<string, string> = {
  pending: "Waiting for the doctor to confirm",
  confirmed: "Confirmed",
  cancelled: "Cancelled",
  completed: "Visit completed",
};

function todayISO() {
  // Local date, not UTC: toISOString() rolls over a day early for IST after
  // 5:30am, which would offer the patient a date the server calls yesterday.
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")}`;
}

function prettyDate(iso: string) {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export default function BookAppointment() {
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [doctorId, setDoctorId] = useState("");
  const [date, setDate] = useState(todayISO);
  const [day, setDay] = useState<DaySlots | null>(null);
  const [slot, setSlot] = useState("");
  const [notes, setNotes] = useState("");

  const [loading, setLoading] = useState(true);
  const [slotsLoading, setSlotsLoading] = useState(false);
  const [booking, setBooking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const loadAppointments = useCallback(() => {
    api
      .get<Appointment[]>("/appointments/my")
      .then((res) => setAppointments(res.data))
      .catch(() => setError("Could not load your appointments."));
  }, []);

  useEffect(() => {
    api
      .get<Doctor[]>("/appointments/doctors")
      .then((res) => setDoctors(res.data))
      .catch(() => setError("Could not load the doctor list."))
      .finally(() => setLoading(false));
    loadAppointments();
  }, [loadAppointments]);

  useEffect(() => {
    if (!doctorId || !date) {
      setDay(null);
      return;
    }
    setSlotsLoading(true);
    setSlot("");
    api
      .get<DaySlots>(`/appointments/doctors/${doctorId}/slots`, { params: { date } })
      .then((res) => setDay(res.data))
      .catch(() => setDay(null))
      .finally(() => setSlotsLoading(false));
  }, [doctorId, date]);

  const selectedDoctor = doctors.find((d) => d.id === doctorId) ?? null;

  const { upcoming, past } = useMemo(() => {
    const isOver = (a: Appointment) =>
      a.status === "cancelled" || a.status === "completed" || a.is_past;
    return {
      upcoming: appointments.filter((a) => !isOver(a)),
      past: appointments.filter(isOver),
    };
  }, [appointments]);

  const handleBook = async () => {
    if (!doctorId || !slot) {
      setError("Pick a doctor and a time first.");
      return;
    }
    setBooking(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await api.post<Appointment>("/appointments/book", {
        doctor_id: doctorId,
        date,
        time_slot: slot,
        notes: notes.trim() || null,
      });
      setSuccess(
        `Requested ${res.data.time_slot_label} on ${prettyDate(date)} with ${
          selectedDoctor?.name ?? "your doctor"
        }. You'll see it confirmed here once they accept.`
      );
      setSlot("");
      setNotes("");
      loadAppointments();
      // Refresh the day so the slot just taken disappears for this patient too.
      const refreshed = await api.get<DaySlots>(
        `/appointments/doctors/${doctorId}/slots`,
        { params: { date } }
      );
      setDay(refreshed.data);
    } catch (err: any) {
      // The API explains exactly why a booking was refused ("that time has
      // already passed", "not one of Dr Iyer's slots"). Showing that beats a
      // generic failure the patient can do nothing with.
      setError(err?.response?.data?.detail ?? "Could not book that slot. Please try another.");
    } finally {
      setBooking(false);
    }
  };

  const handleCancel = async (id: string) => {
    setError(null);
    setSuccess(null);
    try {
      await api.patch(`/appointments/${id}/cancel`);
      setSuccess("Appointment cancelled.");
      loadAppointments();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Could not cancel that appointment.");
    }
  };

  if (loading) return <Spinner label="Loading appointments…" />;

  const renderCard = (a: Appointment, cancellable: boolean) => (
    <Card key={a.id} className="appt-card">
      <div className="appt-card__head">
        <div>
          <p className="appt-card__when">
            {prettyDate(a.date)} · <strong>{a.time_slot_label ?? a.time_slot}</strong>
          </p>
          <p className="appt-card__who">
            {a.doctor?.name ?? "Doctor"}
            {a.doctor?.specialization ? ` · ${a.doctor.specialization}` : ""}
          </p>
        </div>
        <Badge variant={STATUS_VARIANT[a.status] ?? "neutral"}>
          {STATUS_LABEL[a.status] ?? a.status}
        </Badge>
      </div>

      {a.doctor?.clinic_name && <p className="appt-card__meta">{a.doctor.clinic_name}</p>}
      {a.notes && <p className="appt-card__notes">Reason: {a.notes}</p>}
      {a.created_by === "doctor" && a.status === "confirmed" && (
        <p className="appt-card__meta">Scheduled for you by the doctor.</p>
      )}
      {a.doctor_notes && (
        <p className="appt-card__doctornotes">
          <strong>Doctor's note:</strong> {a.doctor_notes}
        </p>
      )}
      {a.status === "cancelled" && a.cancelled_by === "doctor" && (
        <p className="appt-card__meta">Cancelled by the clinic.</p>
      )}

      {cancellable && (
        <Button variant="secondary" onClick={() => handleCancel(a.id)}>
          Cancel appointment
        </Button>
      )}
    </Card>
  );

  return (
    <div className="appointments-page">
      <h1>Appointments</h1>

      {error && <p className="error" role="alert">{error}</p>}
      {success && <p className="success-note" role="status">{success}</p>}

      <section className="wsection">
        <h2 className="wsection__title">Book a visit</h2>

        {doctors.length === 0 ? (
          <EmptyState
            icon="🩺"
            title="No doctors are taking bookings yet"
            description="Once a doctor joins Arogya and completes their profile, they'll appear here."
          />
        ) : (
          <Card className="book-form">
            <label htmlFor="appt-doctor">Doctor</label>
            <select
              id="appt-doctor"
              value={doctorId}
              onChange={(e) => setDoctorId(e.target.value)}
            >
              <option value="">Choose a doctor…</option>
              {doctors.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                  {d.specialization ? ` — ${d.specialization}` : ""}
                </option>
              ))}
            </select>

            {selectedDoctor && (
              <p className="hint">
                {[
                  selectedDoctor.clinic_name,
                  selectedDoctor.languages && `Speaks ${selectedDoctor.languages}`,
                  selectedDoctor.consultation_fee_inr != null &&
                    `Consultation ₹${selectedDoctor.consultation_fee_inr}`,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            )}

            <label htmlFor="appt-date">Date</label>
            <input
              id="appt-date"
              type="date"
              value={date}
              min={todayISO()}
              onChange={(e) => setDate(e.target.value)}
            />

            <label>Time</label>
            {!doctorId ? (
              <p className="hint">Pick a doctor to see their available times.</p>
            ) : slotsLoading ? (
              <Spinner label="Checking availability…" />
            ) : day?.closed_reason ? (
              // Saying WHY the day is empty is the difference between the
              // patient trying another date and giving up.
              <p className="hint">{day.closed_reason}</p>
            ) : day && day.slots.length > 0 ? (
              <div className="slot-grid" role="group" aria-label="Available times">
                {day.slots.map((s) => (
                  <button
                    key={s.time_slot}
                    type="button"
                    className={`slot ${slot === s.time_slot ? "slot--on" : ""} ${
                      s.available ? "" : "slot--off"
                    }`}
                    disabled={!s.available}
                    title={s.reason ?? undefined}
                    onClick={() => setSlot(s.time_slot)}
                  >
                    {s.time_slot}
                  </button>
                ))}
              </div>
            ) : (
              <p className="hint">No times on this date.</p>
            )}

            <label htmlFor="appt-notes">What is the visit about? (optional)</label>
            <input
              id="appt-notes"
              value={notes}
              placeholder="e.g. routine antenatal check"
              onChange={(e) => setNotes(e.target.value)}
            />

            <Button onClick={handleBook} disabled={booking || !slot}>
              {booking ? "Requesting…" : "Request appointment"}
            </Button>
            <p className="hint">
              Requests go to the doctor to confirm. You'll see the status change here — nothing is
              charged through Arogya.
            </p>
          </Card>
        )}
      </section>

      <section className="wsection">
        <h2 className="wsection__title">Upcoming</h2>
        {upcoming.length === 0 ? (
          <EmptyState
            icon="📅"
            title="Nothing booked"
            description="Your upcoming visits will show here once you book one."
          />
        ) : (
          <div className="appt-list">{upcoming.map((a) => renderCard(a, true))}</div>
        )}
      </section>

      {past.length > 0 && (
        <section className="wsection">
          <h2 className="wsection__title">Past and cancelled</h2>
          <div className="appt-list">{past.map((a) => renderCard(a, false))}</div>
        </section>
      )}
    </div>
  );
}
