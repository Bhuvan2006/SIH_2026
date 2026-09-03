import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  type Appointment,
  type Doctor,
  type DoctorPatientSummary,
} from "../api/client";
import { Badge, Button, Card, EmptyState, Spinner } from "../components/ui";

function todayISO() {
  // Local date. toISOString() is UTC, so in IST it returns yesterday's date
  // before 5:30am and the doctor opens on the wrong day's diary.
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")}`;
}

export default function DoctorDashboard() {
  const [doctor, setDoctor] = useState<Doctor | null>(null);
  const [today, setToday] = useState<Appointment[]>([]);
  const [upcoming, setUpcoming] = useState<Appointment[]>([]);
  const [patients, setPatients] = useState<DoctorPatientSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get<Doctor>("/doctor/me"),
      api.get<Appointment[]>("/doctor/appointments", { params: { date: todayISO() } }),
      api.get<Appointment[]>("/doctor/appointments", { params: { upcoming: true } }),
      api.get<DoctorPatientSummary[]>("/doctor/patients"),
    ])
      .then(([d, t, u, p]) => {
        setDoctor(d.data);
        setToday(t.data);
        setUpcoming(u.data);
        setPatients(p.data);
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spinner label="Loading your dashboard…" />;

  const pending = upcoming.filter((a) => a.status === "pending");
  const confirmedToday = today.filter((a) => a.status === "confirmed");

  return (
    <div className="doctor-dashboard">
      <h1>Good day{doctor?.name ? `, ${doctor.name}` : ""} 👋</h1>
      <p className="hint">
        {doctor?.specialization ?? "Set your specialisation in your profile"}
        {doctor?.clinic_name ? ` · ${doctor.clinic_name}` : ""}
      </p>

      {/* A doctor with an incomplete profile is hidden from the patient
          booking list entirely, so saying so is more useful than a silent
          absence of bookings. */}
      {doctor && !doctor.profile_completed && (
        <Card className="warn-card">
          <p>
            <strong>Your profile is incomplete.</strong> Patients can't find you until you add your
            name and specialisation.
          </p>
          <Link to="/doctor/profile">
            <Button>Complete profile</Button>
          </Link>
        </Card>
      )}

      <div className="insights__strip">
        <Card className="icard">
          <p className="icard__label">Today</p>
          <p className="icard__big">{today.length}</p>
          <p className="icard__sub">{confirmedToday.length} confirmed</p>
        </Card>
        <Card className={`icard ${pending.length ? "icard--alert" : ""}`}>
          <p className="icard__label">Awaiting your confirmation</p>
          <p className="icard__big">{pending.length}</p>
          <p className="icard__sub">across all upcoming dates</p>
        </Card>
        <Card className="icard">
          <p className="icard__label">Patients</p>
          <p className="icard__big">{patients.length}</p>
          <p className="icard__sub">seen or booked</p>
        </Card>
      </div>

      <section className="wsection">
        <div className="wsection__head">
          <h2 className="wsection__title">Today's clinic</h2>
          <Link to="/doctor/appointments">
            <Button variant="secondary">Open diary</Button>
          </Link>
        </div>
        {today.length === 0 ? (
          <EmptyState
            icon="📋"
            title="Nothing booked today"
            description="Check your clinic hours if you expected patients — they can only book times you've set."
          />
        ) : (
          <div className="appt-list">
            {today.map((a) => (
              <Card key={a.id} className="appt-card">
                <div className="appt-card__head">
                  <div>
                    <p className="appt-card__when">
                      <strong>{a.time_slot_label ?? a.time_slot}</strong>
                    </p>
                    <p className="appt-card__who">
                      <Link to={`/doctor/patient/${a.patient_id}`}>
                        {a.patient?.name ?? a.patient?.phone ?? "Patient"}
                      </Link>
                      {a.patient?.is_pregnant ? " · pregnant" : ""}
                    </p>
                  </div>
                  <Badge
                    variant={
                      a.status === "confirmed"
                        ? "success"
                        : a.status === "pending"
                          ? "warning"
                          : a.status === "cancelled"
                            ? "danger"
                            : "neutral"
                    }
                  >
                    {a.status}
                  </Badge>
                </div>
                {a.notes && <p className="appt-card__notes">Reason: {a.notes}</p>}
              </Card>
            ))}
          </div>
        )}
      </section>

      <section className="wsection">
        <div className="wsection__head">
          <h2 className="wsection__title">My patients</h2>
        </div>
        {patients.length === 0 ? (
          <p className="hint">
            Patients appear here once they book with you. You can only open a record for someone
            who has an appointment with you.
          </p>
        ) : (
          <ul className="session-list">
            {patients.map((p) => (
              <li key={p.id}>
                <span>
                  <Link to={`/doctor/patient/${p.id}`}>
                    <strong>{p.name ?? p.phone}</strong>
                  </Link>
                  <span className="hint">
                    {" "}
                    · {p.blood_group ?? "blood group unknown"}
                    {p.is_pregnant ? " · pregnant" : ""} · last seen {p.last_appointment}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
