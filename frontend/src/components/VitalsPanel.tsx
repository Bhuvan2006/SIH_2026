import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { Alert, Badge, Button, TextField } from "./ui";

interface Reading {
  date: string | null;
  recorded_at: string | null;
  primary: number;
  secondary: number | null;
  context: string | null;
  source: string;
}

interface MetricSummary {
  metric_type: string;
  latest_value: number | null;
  latest_secondary: number | null;
  latest_at: string | null;
  band_label: string | null;
  band_tone: string | null;
  unit: string;
  count: number;
  average: number | null;
  change_vs_previous: number | null;
  series: Reading[];
}

interface SummaryResponse {
  window_days: number;
  suggested_metrics: string[];
  metrics: Record<string, MetricSummary>;
  adherence_overlay: { date: string; percent: number }[];
  bmi: {
    value: number | null;
    band_label: string | null;
    band_tone: string | null;
    /** Which CDC row the value falls in, e.g. "25.0 – 29.9". */
    range?: string | null;
    /** The whole CDC table, so the card can show where the value sits. */
    scale?: { range: string; label: string; tone: string; upper: number }[];
    // Set instead of a band when the categories don't apply — during
    // pregnancy, where weight gain is expected and BMI stops measuring what
    // the bands describe.
    note?: string | null;
  };
  disclaimer: string;
}

const LABELS: Record<string, string> = {
  blood_pressure: "Blood pressure",
  blood_glucose: "Blood sugar",
  weight: "Weight",
  steps: "Steps",
};

/**
 * Readings plotted against daily dose adherence on one timeline.
 *
 * This is the pairing nothing else in the app can show. Adherence is drawn as
 * a soft background area rather than a second line, so the reading stays the
 * subject and adherence reads as context behind it.
 */
function TrendChart({
  series,
  overlay,
  unit,
}: {
  series: Reading[];
  overlay: { date: string; percent: number }[];
  unit: string;
}) {
  const W = 640;
  const H = 170;
  const PAD = { t: 12, r: 12, b: 22, l: 38 };

  const points = series.filter((s) => s.recorded_at);
  if (points.length < 2) return null;

  const times = points.map((p) => new Date(p.recorded_at as string).getTime());
  const tMin = Math.min(...times);
  const tMax = Math.max(...times);
  const span = tMax - tMin || 1;

  const values = points.flatMap((p) =>
    p.secondary != null ? [p.primary, p.secondary] : [p.primary]
  );
  const vMin = Math.min(...values);
  const vMax = Math.max(...values);
  const pad = (vMax - vMin) * 0.18 || 4;
  const lo = vMin - pad;
  const hi = vMax + pad;

  const x = (t: number) => PAD.l + ((t - tMin) / span) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + (1 - (v - lo) / (hi - lo)) * (H - PAD.t - PAD.b);

  const line = (get: (p: Reading) => number | null) =>
    points
      .map((p, i) => {
        const v = get(p);
        if (v == null) return "";
        return `${i === 0 ? "M" : "L"}${x(new Date(p.recorded_at as string).getTime()).toFixed(1)},${y(v).toFixed(1)}`;
      })
      .filter(Boolean)
      .join(" ");

  // Adherence area, scaled to the chart height independently of the value axis.
  const overlayPts = overlay
    .map((o) => ({ t: new Date(o.date).getTime(), p: o.percent }))
    .filter((o) => o.t >= tMin && o.t <= tMax)
    .sort((a, b) => a.t - b.t);

  const areaPath =
    overlayPts.length > 1
      ? `M${x(overlayPts[0].t).toFixed(1)},${H - PAD.b} ` +
        overlayPts
          .map(
            (o) =>
              `L${x(o.t).toFixed(1)},${(PAD.t + (1 - o.p / 100) * (H - PAD.t - PAD.b)).toFixed(1)}`
          )
          .join(" ") +
        ` L${x(overlayPts[overlayPts.length - 1].t).toFixed(1)},${H - PAD.b} Z`
      : "";

  const last = points[points.length - 1];

  return (
    <div className="trend">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
        aria-label={`Trend of ${points.length} readings with dose adherence behind it`}>
        {[0, 0.5, 1].map((f) => (
          <line key={f} x1={PAD.l} x2={W - PAD.r}
            y1={PAD.t + f * (H - PAD.t - PAD.b)} y2={PAD.t + f * (H - PAD.t - PAD.b)}
            className="trend__grid" />
        ))}
        {areaPath && <path d={areaPath} className="trend__area" />}
        {last.secondary != null && <path d={line((p) => p.secondary)} className="trend__line trend__line--sec" />}
        <path d={line((p) => p.primary)} className="trend__line" />
        {points.map((p, i) => (
          <circle key={i} cx={x(new Date(p.recorded_at as string).getTime())} cy={y(p.primary)}
            r={i === points.length - 1 ? 4 : 2.5}
            className={i === points.length - 1 ? "trend__dot trend__dot--last" : "trend__dot"} />
        ))}
        <text x={PAD.l - 6} y={y(hi) + 10} className="trend__axis" textAnchor="end">{Math.round(hi)}</text>
        <text x={PAD.l - 6} y={y(lo)} className="trend__axis" textAnchor="end">{Math.round(lo)}</text>
      </svg>
      <p className="trend__legend">
        <span className="trend__key trend__key--line" /> {unit}
        {last.secondary != null && (
          <>
            <span className="trend__key trend__key--sec" /> diastolic
          </>
        )}
        <span className="trend__key trend__key--area" /> dose adherence
      </p>
    </div>
  );
}

export default function VitalsPanel() {
  const [data, setData] = useState<SummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [type, setType] = useState("blood_pressure");
  const [v1, setV1] = useState("");
  const [v2, setV2] = useState("");
  const [ctx, setCtx] = useState("fasting");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () =>
      api
        .get<SummaryResponse>("/metrics/summary")
        .then((r) => setData(r.data))
        .catch(() => setData(null))
        .finally(() => setLoading(false)),
    []
  );

  useEffect(() => {
    load();
  }, [load]);

  const shown = useMemo(
    () => (data ? data.suggested_metrics.filter((m) => data.metrics[m]) : []),
    [data]
  );

  const save = async () => {
    setError(null);
    const primary = Number(v1);
    if (!v1 || Number.isNaN(primary)) return setError("Enter a number.");
    if (type === "blood_pressure" && (!v2 || Number.isNaN(Number(v2))))
      return setError("Blood pressure needs both numbers, e.g. 120 over 80.");

    setSaving(true);
    try {
      await api.post("/metrics", {
        metric_type: type,
        value_primary: primary,
        value_secondary: type === "blood_pressure" ? Number(v2) : null,
        context: type === "blood_glucose" ? ctx : null,
      });
      setV1("");
      setV2("");
      setOpen(false);
      await load();
    } catch {
      setError("Could not save that reading. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  if (loading || !data) return null;

  const hasAny = shown.some((m) => data.metrics[m].count > 0);
  // BMI comes from the height and weight on the profile, not from readings.
  // It was inside the readings-only branch, so a patient who filled in their
  // profile but had never logged a BP saw nothing at all.
  const hasBmi = data.bmi.value != null;

  return (
    <section className="vitals">
      <div className="vitals__head">
        <div>
          <h2 className="vitals__title">Your readings</h2>
          <p className="vitals__sub">
            Blood pressure and sugar from your own monitor — the numbers your doctor asks about.
          </p>
        </div>
        <Button size="sm" variant={open ? "ghost" : "primary"} onClick={() => setOpen((o) => !o)}>
          {open ? "Cancel" : "+ Add reading"}
        </Button>
      </div>

      {open && (
        <div className="vitals__form">
          <div className="ui-field">
            <label className="ui-field__label" htmlFor="metric-type">What are you recording?</label>
            <select id="metric-type" className="ui-field__input" value={type}
              onChange={(e) => setType(e.target.value)}>
              <option value="blood_pressure">Blood pressure</option>
              <option value="blood_glucose">Blood sugar</option>
              <option value="weight">Weight</option>
              <option value="steps">Steps today</option>
            </select>
          </div>

          <TextField
            label={
              type === "blood_pressure" ? "Systolic (upper)"
                : type === "blood_glucose" ? "Reading (mg/dL)"
                : type === "weight" ? "Weight (kg)" : "Steps"
            }
            type="number" inputMode="decimal" value={v1}
            onChange={(e) => setV1(e.target.value)}
          />

          {type === "blood_pressure" && (
            <TextField label="Diastolic (lower)" type="number" inputMode="decimal"
              value={v2} onChange={(e) => setV2(e.target.value)} />
          )}

          {type === "blood_glucose" && (
            <div className="ui-field">
              <label className="ui-field__label" htmlFor="glucose-ctx">When was it taken?</label>
              <select id="glucose-ctx" className="ui-field__input" value={ctx}
                onChange={(e) => setCtx(e.target.value)}>
                <option value="fasting">Fasting (before eating)</option>
                <option value="post_meal">After a meal</option>
                <option value="random">Any other time</option>
              </select>
            </div>
          )}

          <div className="vitals__formactions">
            <Button loading={saving} onClick={save}>Save reading</Button>
          </div>
          {error && <Alert variant="danger">{error}</Alert>}
        </div>
      )}

      {!hasAny && (
        <div className="vitals__empty">
          <p className="vitals__empty-title">No readings yet</p>
          <p className="vitals__empty-body">
            If you check your blood pressure or sugar at home, add a reading and this will chart it
            against how consistently you've been taking your medicines.
          </p>
        </div>
      )}

      {(hasAny || hasBmi) && (
        <div className="vitals__grid">
          {shown.map((key) => {
            const m = data.metrics[key];
            if (m.count === 0) return null;
            const val =
              m.latest_secondary != null
                ? `${m.latest_value}/${m.latest_secondary}`
                : `${m.latest_value}`;
            return (
              <article key={key} className="vcard">
                <div className="vcard__head">
                  <p className="vcard__label">{LABELS[key] ?? key}</p>
                  {m.band_label && (
                    <Badge
                      variant={
                        m.band_tone === "good" ? "success"
                          : m.band_tone === "bad" ? "danger" : "warning"
                      }
                    >
                      {m.band_label}
                    </Badge>
                  )}
                </div>
                <p className="vcard__value">
                  {val}
                  <span className="vcard__unit"> {m.unit}</span>
                </p>
                <p className="vcard__meta">
                  {m.count} reading{m.count === 1 ? "" : "s"} · average {m.average}
                  {/* Direction is always shown; colour only where a direction
                      genuinely means better or worse. A rise in weight is red
                      for nobody in particular — it is expected in pregnancy,
                      and wanted in an underweight patient — so weight stays
                      neutral rather than scolding the reader. */}
                  {m.change_vs_previous != null && m.change_vs_previous !== 0 && (
                    <span
                      className={
                        m.metric_type === "weight"
                          ? "vcard__flat"
                          : m.change_vs_previous > 0
                            ? "vcard__up"
                            : "vcard__down"
                      }
                    >
                      {" "}
                      {m.change_vs_previous > 0 ? "▲" : "▼"} {Math.abs(m.change_vs_previous)} vs last
                    </span>
                  )}
                </p>
                <TrendChart series={m.series} overlay={data.adherence_overlay} unit={m.unit} />
              </article>
            );
          })}

          {data.bmi.value && (
            <article className="vcard vcard--compact">
              <div className="vcard__head">
                <p className="vcard__label">BMI</p>
                {/* No band during pregnancy: rating a pregnant woman
                    "Overweight" for expected weight gain is both wrong and
                    the kind of thing a patient acts on. */}
                {data.bmi.band_label && (
                  <Badge
                    variant={
                      data.bmi.band_tone === "good" ? "success"
                        : data.bmi.band_tone === "bad" ? "danger" : "warning"
                    }
                  >
                    {data.bmi.band_label}
                  </Badge>
                )}
              </div>
              <p className="vcard__value">{data.bmi.value}</p>
              {data.bmi.range && (
                <p className="vcard__meta">
                  Your BMI falls in the <strong>{data.bmi.range}</strong> range.
                </p>
              )}

              {/* The CDC scale with the patient's own row marked. A category
                  on its own ("Overweight") says nothing about how far from the
                  next band they are; the table does. */}
              {data.bmi.scale && data.bmi.range && (
                <table className="bmi-scale">
                  <caption className="bmi-scale__caption">
                    BMI ranges for adults · Centers for Disease Control and Prevention
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">BMI</th>
                      <th scope="col">Weight status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.bmi.scale.map((row) => {
                      const isYou = row.range === data.bmi.range;
                      return (
                        <tr
                          key={row.range}
                          className={isYou ? "bmi-scale__row--you" : undefined}
                          aria-current={isYou ? "true" : undefined}
                        >
                          <td>{row.range}</td>
                          <td>
                            {row.label}
                            {isYou && <span className="bmi-scale__you"> ← you</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}

              <p className="vcard__meta">
                {data.bmi.note ??
                  "From the height and weight on your profile. BMI is a rough screen, not a diagnosis — it says nothing about muscle, build, or where weight is carried."}
              </p>
            </article>
          )}
        </div>
      )}

      {(hasAny || hasBmi) && <p className="vitals__disclaimer">{data.disclaimer}</p>}
    </section>
  );
}
