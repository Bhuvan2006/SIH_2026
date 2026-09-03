import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type DashboardInsights } from "../api/client";
import { Badge, Spinner } from "./ui";

/** Ring showing dose adherence against the 80% reference mark. */
function AdherenceRing({ percent, target }: { percent: number; target: number }) {
  const R = 52;
  const C = 2 * Math.PI * R;
  const pct = Math.max(0, Math.min(100, percent));
  const tone = pct >= target ? "good" : pct >= target - 15 ? "warn" : "bad";

  // The target tick sits on the same circle so "how far off am I" is a
  // distance you can see, not arithmetic you have to do.
  const targetAngle = (target / 100) * 360 - 90;
  const rad = (targetAngle * Math.PI) / 180;
  const tx = 70 + Math.cos(rad) * R;
  const ty = 70 + Math.sin(rad) * R;

  return (
    <div className="ring">
      <svg viewBox="0 0 140 140" role="img" aria-label={`${pct}% of doses taken, target ${target}%`}>
        <circle cx="70" cy="70" r={R} className="ring__track" />
        <circle
          cx="70"
          cy="70"
          r={R}
          className={`ring__arc ring__arc--${tone}`}
          strokeDasharray={`${(pct / 100) * C} ${C}`}
          transform="rotate(-90 70 70)"
        />
        <circle cx={tx} cy={ty} r="4" className="ring__target" />
        <text x="70" y="66" className="ring__value" textAnchor="middle">
          {pct}%
        </text>
        <text x="70" y="86" className="ring__unit" textAnchor="middle">
          doses taken
        </text>
      </svg>
    </div>
  );
}

/** 30-day daily adherence, one bar per day. */
function DailyBars({ series }: { series: { date: string; expected: number; taken: number }[] }) {
  if (series.length === 0) return null;
  return (
    <div className="daybars" role="img" aria-label={`Daily adherence over ${series.length} days`}>
      {series.map((d) => {
        const ratio = d.expected ? d.taken / d.expected : 0;
        const tone = ratio === 1 ? "full" : ratio > 0 ? "part" : "none";
        return (
          <span
            key={d.date}
            className={`daybars__bar daybars__bar--${tone}`}
            style={{ height: `${Math.max(12, ratio * 100)}%` }}
            title={`${new Date(d.date).toLocaleDateString()} — ${d.taken}/${d.expected} taken`}
          />
        );
      })}
    </div>
  );
}

export default function InsightsPanel() {
  const [data, setData] = useState<DashboardInsights | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<DashboardInsights>("/reminders/insights")
      .then((res) => setData(res.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="insights__loading">
        <Spinner label="Working out your insights…" />
      </div>
    );
  }
  if (!data) return null;

  const { adherence, streak, refills, savings, per_medicine, worst_slot } = data;
  const soonest = refills[0];
  const belowTarget = adherence.percent < adherence.target_percent;

  // Percentages from two or three logged days are noise. Say so rather than
  // rendering a confident-looking 100%.
  if (!data.has_enough_data) {
    return (
      <section className="insights">
        <div className="insights__empty">
          <span className="insights__empty-icon" aria-hidden="true">
            📈
          </span>
          <div>
            <p className="insights__empty-title">Your insights are still building</p>
            <p className="insights__empty-body">
              {data.days_tracked === 0
                ? "Once you start marking doses taken, this is where you'll see how you're tracking."
                : `Only ${data.days_tracked} day${data.days_tracked === 1 ? "" : "s"} logged so far — a few more and the numbers here will actually mean something.`}
            </p>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="insights">
      <div className="insights__strip">
        {/* Adherence */}
        <article className="icard icard--wide">
          <p className="icard__label">Last {adherence.days_total} days</p>
          <div className="icard__ringrow">
            <AdherenceRing percent={adherence.percent} target={adherence.target_percent} />
            <div>
              <p className="icard__lead">
                {belowTarget ? (
                  <>
                    Below the <strong>{adherence.target_percent}%</strong> mark
                  </>
                ) : (
                  <>
                    Above the <strong>{adherence.target_percent}%</strong> mark
                  </>
                )}
              </p>
              <p className="icard__sub">
                {adherence.doses_taken} of {adherence.doses_expected} doses taken ·{" "}
                {adherence.days_covered} full days
              </p>
              <p className="icard__note">
                {adherence.target_percent}% is the level clinicians look for before a long-term
                medicine reliably does its job.
              </p>
            </div>
          </div>
          <DailyBars series={adherence.daily_series} />
        </article>

        {/* Streak */}
        <article className="icard">
          <p className="icard__label">Streak</p>
          <p className="icard__big">
            {streak.current}
            <span className="icard__bigunit">
              {streak.current === 1 ? " day" : " days"}
            </span>
          </p>
          <p className="icard__sub">
            {streak.best > streak.current ? `Your best was ${streak.best} days` : "That's your best run"}
          </p>
          <p className="icard__note">Every dose taken, day after day.</p>
        </article>

        {/* Refill runway */}
        <article className={`icard ${soonest && soonest.days_left <= 7 ? "icard--alert" : ""}`}>
          <p className="icard__label">Next to run out</p>
          {soonest ? (
            <>
              <p className="icard__big">
                {soonest.days_left < 0 ? 0 : soonest.days_left}
                <span className="icard__bigunit">
                  {Math.abs(soonest.days_left) === 1 ? " day" : " days"}
                </span>
              </p>
              <p className="icard__sub">
                {soonest.name}
                {soonest.days_left < 0 ? " — already finished" : ""}
              </p>
              <p className="icard__note">
                Runs out {new Date(soonest.runs_out_on).toLocaleDateString()}. Arrange a refill
                before then.
              </p>
            </>
          ) : (
            <>
              <p className="icard__big icard__big--muted">—</p>
              <p className="icard__sub">No course end dates recorded</p>
              <p className="icard__note">
                Add a duration when confirming a prescription and this will track it.
              </p>
            </>
          )}
        </article>
      </div>

      {/* Per-medicine, worst first */}
      {per_medicine.length > 0 && (
        <article className="icard icard--full">
          <div className="icard__head">
            <p className="icard__label">By medicine</p>
            {per_medicine[0].percent < adherence.target_percent && (
              <Badge variant="warning">{per_medicine[0].name} needs attention</Badge>
            )}
          </div>
          <ul className="medbars">
            {per_medicine.map((m) => {
              const tone =
                m.percent >= adherence.target_percent
                  ? "good"
                  : m.percent >= adherence.target_percent - 15
                    ? "warn"
                    : "bad";
              return (
                <li key={m.medication_id} className="medbars__row">
                  <span className="medbars__name">{m.name}</span>
                  <span className="medbars__track">
                    <span
                      className={`medbars__fill medbars__fill--${tone}`}
                      style={{ width: `${m.percent}%` }}
                    />
                    <span
                      className="medbars__target"
                      style={{ left: `${adherence.target_percent}%` }}
                      aria-hidden="true"
                    />
                  </span>
                  <span className="medbars__pct">{m.percent}%</span>
                  <span className="medbars__count">
                    {m.missed} missed
                  </span>
                </li>
              );
            })}
          </ul>

          {worst_slot && (
            <p className="insight-line">
              💡 Your <strong>{worst_slot.time_of_day}</strong> dose is the one most often missed —{" "}
              {worst_slot.missed} of {worst_slot.total}. If that time doesn't fit your routine, you
              can change it on <Link to="/medications">your medicines</Link>.
            </p>
          )}
        </article>
      )}

      {/* Generic savings */}
      {savings.items.length > 0 && (
        <article className="icard icard--full">
          <div className="icard__head">
            <p className="icard__label">Cheaper equivalents</p>
            <Badge variant="success">₹{savings.total_per_pack.toFixed(0)} per pack</Badge>
          </div>
          <ul className="savelist">
            {savings.items.map((s) => (
              <li key={s.medication_id} className="savelist__row">
                <span className="savelist__name">{s.name}</span>
                <span className="savelist__swap">
                  <span className="savelist__from">
                    {s.current_product} ₹{s.current_price.toFixed(0)}
                  </span>
                  <span aria-hidden="true"> → </span>
                  <span className="savelist__to">
                    {s.cheapest_product} ₹{s.cheapest_price.toFixed(0)}
                  </span>
                </span>
                <span className="savelist__save">save ₹{s.saving_per_pack.toFixed(0)}</span>
              </li>
            ))}
          </ul>
          <p className="icard__note">
            Same composition and strength, per {savings.items[0].unit}. Informational only — ask your
            pharmacist before switching brands.
          </p>
        </article>
      )}
    </section>
  );
}
