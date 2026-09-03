import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { Alert, Badge, Button, EmptyState, Spinner, TextField } from "../components/ui";

interface EquipmentGuide {
  id: string;
  icon: string;
  title: string;
  summary: string;
  why_it_matters: string;
  before_you_start: string[];
  steps: string[];
  common_mistakes: string[];
  when_to_worry: string;
  source: string;
  recommended?: boolean;
}

interface VideoTopic {
  id: string;
  icon: string;
  title: string;
  blurb: string;
  channel: string;
  youtube_url: string;
  video_id?: string | null;
  recommended?: boolean;
}

interface WellnessHub {
  equipment_guides: EquipmentGuide[];
  video_topics: VideoTopic[];
  activity_ideas: { icon: string; title: string; detail: string; target: string }[];
  awareness: { icon: string; title: string; detail: string }[];
  personalised_for: string[];
  disclaimer: string;
}

interface HealthEvent {
  id: string;
  title: string;
  description: string | null;
  event_type: string;
  starts_at: string;
  ends_at: string | null;
  location_name: string | null;
  address: string | null;
  organiser: string | null;
  contact: string | null;
  is_free: boolean;
  is_mine: boolean;
}

const EVENT_STYLE: Record<string, { icon: string; label: string }> = {
  walk: { icon: "🚶", label: "Walk" },
  yoga: { icon: "🧘", label: "Yoga" },
  screening: { icon: "🩺", label: "Screening" },
  talk: { icon: "🎤", label: "Talk" },
  camp: { icon: "⛺", label: "Camp" },
  other: { icon: "📅", label: "Event" },
};

interface NearbyPlace {
  name: string | null;
  address: string | null;
  type: string | null;
  rating: number | null;
  maps_url: string | null;
}

/** One expandable how-to card for a piece of home medical equipment. */
function GuideCard({ guide }: { guide: EquipmentGuide }) {
  const [open, setOpen] = useState(false);

  return (
    <article className={`guide ${guide.recommended ? "guide--rec" : ""}`}>
      <button
        type="button"
        className="guide__head"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={`guide-${guide.id}`}
      >
        <span className="guide__icon" aria-hidden="true">{guide.icon}</span>
        <span className="guide__headtext">
          <span className="guide__title">
            {guide.title}
            {guide.recommended && <Badge variant="primary">For you</Badge>}
          </span>
          <span className="guide__summary">{guide.summary}</span>
        </span>
        <span className="guide__chev" aria-hidden="true">{open ? "−" : "+"}</span>
      </button>

      {open && (
        <div className="guide__body" id={`guide-${guide.id}`}>
          <p className="guide__why">{guide.why_it_matters}</p>

          <h4 className="guide__sub">Before you start</h4>
          <ul className="guide__list">
            {guide.before_you_start.map((s, i) => <li key={i}>{s}</li>)}
          </ul>

          <h4 className="guide__sub">Step by step</h4>
          <ol className="guide__steps">
            {guide.steps.map((s, i) => <li key={i}>{s}</li>)}
          </ol>

          <h4 className="guide__sub">Common mistakes</h4>
          <ul className="guide__list guide__list--warn">
            {guide.common_mistakes.map((s, i) => <li key={i}>{s}</li>)}
          </ul>

          <div className="guide__worry">
            <strong>When to get help:</strong> {guide.when_to_worry}
          </div>
          <p className="guide__source">Source: {guide.source}</p>
        </div>
      )}
    </article>
  );
}

export default function Wellness() {
  const { t } = useTranslation();
  const [hub, setHub] = useState<WellnessHub | null>(null);
  const [loading, setLoading] = useState(true);

  const [places, setPlaces] = useState<NearbyPlace[]>([]);
  const [placesMsg, setPlacesMsg] = useState<string | null>(null);
  const [placesLoading, setPlacesLoading] = useState(false);

  // ---- Community events ----
  const [events, setEvents] = useState<HealthEvent[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [posting, setPosting] = useState(false);
  const [eventError, setEventError] = useState<string | null>(null);
  const [form, setForm] = useState({
    title: "",
    event_type: "walk",
    starts_at: "",
    location_name: "",
    address: "",
    organiser: "",
    contact: "",
    description: "",
  });

  const loadEvents = () =>
    api
      .get<HealthEvent[]>("/wellness/events")
      .then((r) => setEvents(r.data))
      .catch(() => setEvents([]));

  useEffect(() => {
    api
      .get<WellnessHub>("/wellness")
      .then((r) => setHub(r.data))
      .catch(() => setHub(null))
      .finally(() => setLoading(false));
    loadEvents();
  }, []);

  const postEvent = async () => {
    setEventError(null);
    if (!form.title.trim()) return setEventError("Give the event a name.");
    if (!form.starts_at) return setEventError("Pick a date and time.");

    setPosting(true);
    try {
      await api.post("/wellness/events", {
        ...form,
        title: form.title.trim(),
        starts_at: new Date(form.starts_at).toISOString(),
      });
      setForm({
        title: "", event_type: "walk", starts_at: "", location_name: "",
        address: "", organiser: "", contact: "", description: "",
      });
      setShowForm(false);
      await loadEvents();
    } catch {
      setEventError("Could not post that event. Please try again.");
    } finally {
      setPosting(false);
    }
  };

  const removeEvent = async (id: string) => {
    if (!window.confirm("Remove this event from the noticeboard?")) return;
    await api.delete(`/wellness/events/${id}`);
    setEvents((prev) => prev.filter((e) => e.id !== id));
  };

  const findNearby = () => {
    setPlacesLoading(true);
    setPlacesMsg(null);

    const run = (lat: number, lon: number) =>
      api
        .get("/wellness/nearby-activity", { params: { lat, lon } })
        .then((r) => {
          setPlaces(r.data.places ?? []);
          if (!r.data.available) setPlacesMsg(r.data.reason);
          else if ((r.data.places ?? []).length === 0)
            setPlacesMsg("Nothing found within 5km — try again from a different location.");
        })
        .catch(() => setPlacesMsg("Could not load places just now."))
        .finally(() => setPlacesLoading(false));

    if (!navigator.geolocation) {
      // Bengaluru city centre, matching the pharmacy locator's fallback.
      run(12.9716, 77.5946);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => run(pos.coords.latitude, pos.coords.longitude),
      () => {
        setPlacesMsg("Location access was declined — showing results for Bengaluru city centre.");
        run(12.9716, 77.5946);
      },
      { timeout: 8000 }
    );
  };

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: "center" }}>
        <Spinner size="lg" label="Loading the health hub…" />
      </div>
    );
  }
  if (!hub) return <Alert variant="danger">Could not load the health hub. Please refresh.</Alert>;

  return (
    <div>
      <div className="dash-hero animate-in">
        <h1>{t("wellness")}</h1>
        <p>
          Learn to use your home health kit properly, watch short explainers, and find somewhere
          nearby to get moving.
        </p>
      </div>

      {/* ---------- Community events ----------
          Placed first because it is the only time-sensitive thing on the page:
          a screening camp on Saturday is useless read on Sunday. */}
      <section className="wsection">
        <div className="wsection__head">
          <div>
            <h2 className="wsection__title">What&rsquo;s on near you</h2>
            <p className="wsection__sub">
              Walks, camps and classes posted by people locally. Anyone can add one — past events
              drop off automatically.
            </p>
          </div>
          <Button size="sm" variant={showForm ? "ghost" : "primary"} onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "+ Post an event"}
          </Button>
        </div>

        {showForm && (
          <div className="event-form">
            <TextField
              label="What is it?"
              placeholder="Sunday morning walking group"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
            />
            <div className="ui-field">
              <label className="ui-field__label" htmlFor="ev-type">Type</label>
              <select
                id="ev-type"
                className="ui-field__input"
                value={form.event_type}
                onChange={(e) => setForm({ ...form, event_type: e.target.value })}
              >
                <option value="walk">Walk / run</option>
                <option value="yoga">Yoga / exercise class</option>
                <option value="screening">Health screening</option>
                <option value="camp">Health camp</option>
                <option value="talk">Talk / support group</option>
                <option value="other">Something else</option>
              </select>
            </div>
            <TextField
              label="When"
              type="datetime-local"
              value={form.starts_at}
              onChange={(e) => setForm({ ...form, starts_at: e.target.value })}
            />
            <TextField
              label="Where"
              placeholder="Lalbagh, main gate"
              value={form.location_name}
              onChange={(e) => setForm({ ...form, location_name: e.target.value })}
            />
            <TextField
              label="Who's organising"
              placeholder="Name or group"
              value={form.organiser}
              onChange={(e) => setForm({ ...form, organiser: e.target.value })}
            />
            <TextField
              label="Contact (optional)"
              placeholder="Phone or website"
              value={form.contact}
              onChange={(e) => setForm({ ...form, contact: e.target.value })}
            />
            <div className="event-form__wide">
              <TextField
                label="Details (optional)"
                placeholder="Who it's for, what to bring, how long it runs"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </div>
            <div className="event-form__actions">
              <Button loading={posting} onClick={postEvent}>Post event</Button>
            </div>
            {eventError && <Alert variant="danger" className="event-form__wide">{eventError}</Alert>}
            <Alert variant="info" className="event-form__wide">
              Anything you post here is visible to every Arogya user. Your name and phone number are
              never shown — only the organiser and contact details you type above.
            </Alert>
          </div>
        )}

        {events.length === 0 ? (
          <EmptyState
            icon="📅"
            title="Nothing posted yet"
            description="Know of a morning walk group, a free screening camp, or a yoga class? Post it so others nearby can join."
            action={<Button onClick={() => setShowForm(true)}>Post an event</Button>}
          />
        ) : (
          <ul className="event-list">
            {events.map((ev) => {
              const style = EVENT_STYLE[ev.event_type] ?? EVENT_STYLE.other;
              const when = new Date(ev.starts_at);
              const days = Math.round((when.getTime() - Date.now()) / 86400000);
              return (
                <li key={ev.id} className="event">
                  <div className="event__date" aria-hidden="true">
                    <span className="event__day">{when.getDate()}</span>
                    <span className="event__mon">
                      {when.toLocaleString(undefined, { month: "short" })}
                    </span>
                  </div>
                  <div className="event__body">
                    <div className="event__top">
                      <span className="event__title">
                        <span aria-hidden="true">{style.icon}</span> {ev.title}
                      </span>
                      <Badge variant="neutral">{style.label}</Badge>
                      {ev.is_free && <Badge variant="success">Free</Badge>}
                      {ev.is_mine && <Badge variant="primary">Posted by you</Badge>}
                    </div>
                    <p className="event__when">
                      {when.toLocaleString(undefined, {
                        weekday: "long", hour: "numeric", minute: "2-digit",
                      })}
                      {days >= 0 && (
                        <span className="event__soon">
                          {" · "}
                          {days === 0 ? "today" : days === 1 ? "tomorrow" : `in ${days} days`}
                        </span>
                      )}
                    </p>
                    {(ev.location_name || ev.address) && (
                      <p className="event__place">
                        📍 {ev.location_name}
                        {ev.address && <span className="event__addr"> · {ev.address}</span>}
                      </p>
                    )}
                    {ev.description && <p className="event__desc">{ev.description}</p>}
                    <p className="event__meta">
                      {ev.organiser && <>Organised by {ev.organiser}</>}
                      {ev.contact && <> · {ev.contact}</>}
                    </p>
                  </div>
                  {ev.is_mine && (
                    <Button variant="ghost" size="sm" onClick={() => removeEvent(ev.id)}>
                      Remove
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* ---------- Awareness ---------- */}
      <section className="wsection">
        <h2 className="wsection__title">Worth knowing</h2>
        <div className="aware-grid">
          {hub.awareness.map((a, i) => (
            <article key={i} className="aware">
              <span className="aware__icon" aria-hidden="true">{a.icon}</span>
              <h3 className="aware__title">{a.title}</h3>
              <p className="aware__detail">{a.detail}</p>
            </article>
          ))}
        </div>
      </section>

      {/* ---------- Equipment guides ---------- */}
      <section className="wsection">
        <div className="wsection__head">
          <div>
            <h2 className="wsection__title">Using your home health kit</h2>
            <p className="wsection__sub">
              Technique changes the number more than most people realise. Tap a device to see how to
              measure correctly.
            </p>
          </div>
        </div>
        <div className="guide-list">
          {hub.equipment_guides.map((g) => <GuideCard key={g.id} guide={g} />)}
        </div>
      </section>

      {/* ---------- Videos ---------- */}
      <section className="wsection">
        <div className="wsection__head">
          <div>
            <h2 className="wsection__title">Watch and learn</h2>
            <p className="wsection__sub">
              Short explainers from health authorities. Each opens on YouTube.
            </p>
          </div>
        </div>
        <div className="video-grid">
          {hub.video_topics.map((v) => (
            <a key={v.id} className={`vtile ${v.recommended ? "vtile--rec" : ""}`}
              href={v.youtube_url} target="_blank" rel="noopener noreferrer">
              <span className="vtile__thumb" aria-hidden="true">
                <span className="vtile__icon">{v.icon}</span>
                <span className="vtile__play">▶</span>
              </span>
              <span className="vtile__body">
                <span className="vtile__title">
                  {v.title}
                  {v.recommended && <Badge variant="primary">For you</Badge>}
                </span>
                <span className="vtile__blurb">{v.blurb}</span>
                <span className="vtile__channel">{v.channel}</span>
              </span>
            </a>
          ))}
        </div>
      </section>

      {/* ---------- Move more ---------- */}
      <section className="wsection">
        <h2 className="wsection__title">Getting active</h2>
        <div className="act-grid">
          {hub.activity_ideas.map((a, i) => (
            <article key={i} className="act">
              <span className="act__icon" aria-hidden="true">{a.icon}</span>
              <div>
                <h3 className="act__title">{a.title}</h3>
                <p className="act__detail">{a.detail}</p>
                <Badge variant="success">{a.target}</Badge>
              </div>
            </article>
          ))}
        </div>
      </section>

      {/* ---------- Nearby places ---------- */}
      <section className="wsection">
        <div className="wsection__head">
          <div>
            <h2 className="wsection__title">Places to be active near you</h2>
            <p className="wsection__sub">
              Parks, gyms and yoga studios within 5km. Parks come first — they're free.
            </p>
          </div>
          <Button size="sm" loading={placesLoading} onClick={findNearby}>
            Find near me
          </Button>
        </div>

        {placesMsg && <Alert variant="info">{placesMsg}</Alert>}

        {places.length > 0 ? (
          <ul className="place-list">
            {places.map((p, i) => (
              <li key={i} className="place">
                <div>
                  <span className="place__name">{p.name}</span>
                  {p.type && <Badge variant="neutral">{p.type}</Badge>}
                  {p.address && <div className="place__addr">{p.address}</div>}
                </div>
                <div className="place__right">
                  {p.rating != null && <span className="place__rating">★ {p.rating}</span>}
                  {p.maps_url && (
                    <a className="btn-link" href={p.maps_url} target="_blank" rel="noopener noreferrer">
                      Directions
                    </a>
                  )}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          !placesMsg && (
            <EmptyState
              icon="🏃"
              title="Find somewhere to walk or exercise"
              description="Tap “Find near me” to see parks, gyms and yoga studios nearby."
            />
          )
        )}
      </section>

      <p className="wellness__disclaimer">{hub.disclaimer}</p>
    </div>
  );
}
