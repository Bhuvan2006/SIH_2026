import { useState } from "react";
import type { ExtractedMedication, SafetyFlag } from "../api/client";
import { Badge } from "./ui";

const SEVERITY_ORDER: Record<string, number> = { critical: 0, warning: 1, info: 2 };

const SEVERITY_ICON: Record<string, string> = {
  critical: "⛔",
  warning: "⚠️",
  info: "ℹ️",
};

export function SafetyFlagList({ flags }: { flags: SafetyFlag[] }) {
  if (flags.length === 0) return null;
  const sorted = [...flags].sort(
    (a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9)
  );

  return (
    <div className="safety-list">
      {sorted.map((f, i) => (
        <div
          key={i}
          className={`safety-flag safety-flag--${f.severity}`}
          // Critical flags interrupt; softer ones are announced politely.
          role={f.severity === "critical" ? "alert" : "status"}
        >
          <span className="safety-flag__icon" aria-hidden="true">
            {SEVERITY_ICON[f.severity] ?? "•"}
          </span>
          <div>
            <p className="safety-flag__title">{f.title}</p>
            <p className="safety-flag__detail">{f.detail}</p>
            <p className="safety-flag__action">👉 {f.action}</p>
            {f.source && <p className="safety-flag__source">Source: {f.source}</p>}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Per-medicine review block shown under the editable prescription table:
 * safety screening first, then the price comparison.
 *
 * Order is deliberate. "This clashes with your penicillin allergy" must be
 * read before "here is a cheaper brand" -- money is never the first thing a
 * patient should weigh against a safety warning.
 */
export default function MedicineReviewCard({ med }: { med: ExtractedMedication }) {
  const [showAllPrices, setShowAllPrices] = useState(false);

  const flags = med.safety_flags ?? [];
  // Undefined means an older response that predates the bulk catalogue, where
  // every medicine did come from the curated set.
  const hasSafetyData = med.has_safety_data !== false;
  const options = med.price_options ?? [];
  const worst = flags.reduce<string | null>(
    (acc, f) =>
      acc === null || (SEVERITY_ORDER[f.severity] ?? 9) < (SEVERITY_ORDER[acc] ?? 9) ? f.severity : acc,
    null
  );

  const name = med.matched_generic_name || med.raw_name;
  const shown = showAllPrices ? options : options.slice(0, 3);
  const costliest = options.length ? options[options.length - 1] : null;

  // Build the headline verdict from the most serious reason, so the sentence
  // names the actual cause ("your penicillin allergy") rather than a generic
  // "there is a problem".
  const reasons = {
    pregnancy: flags.filter((f) => f.kind === "pregnancy"),
    banned: flags.filter((f) => f.kind === "banned"),
    allergy: flags.filter((f) => f.kind === "allergy"),
    condition: flags.filter((f) => f.kind === "contraindication"),
    duplicate: flags.filter((f) => f.kind === "duplicate"),
    interaction: flags.filter((f) => f.kind === "interaction"),
    menopause: flags.filter((f) => f.kind === "menopause"),
  };

  let verdict: string | null = null;
  // Pregnancy leads: it is the reason with the narrowest window to act on and
  // the least reversible consequence if missed.
  if (reasons.pregnancy.length > 0) {
    verdict = `Do not take this before speaking to your doctor — it is not normally used in pregnancy.`;
  } else if (reasons.allergy.length > 0) {
    verdict = `Do not take this without asking your doctor — it matches an allergy on your record.`;
  } else if (reasons.banned.length > 0) {
    verdict = `This medicine is banned or restricted in India. Confirm with your doctor before taking it.`;
  } else if (reasons.condition.length > 0) {
    verdict = `You may not be able to take this because of a health condition on your record — check with your doctor first.`;
  } else if (reasons.interaction.length > 0) {
    verdict = `This may clash with another medicine on the same prescription — ask your doctor.`;
  } else if (reasons.duplicate.length > 0) {
    verdict = `This overlaps with another medicine here — check both are meant to be taken together.`;
  } else if (reasons.menopause.length > 0) {
    // Phrased as "keep taking it, but talk about it". This medicine is usually
    // cancer therapy, so a verdict that reads like a warning to stop would be
    // the most dangerous sentence on the page.
    verdict = `Keep taking this as prescribed — but it can make menopausal symptoms worse, so tell your doctor how you're coping.`;
  }

  return (
    <article className={`med-review ${worst ? `med-review--${worst}` : ""}`}>
      <header className="med-review__head">
        <div>
          <h3 className="med-review__name">{name}</h3>
          <p className="med-review__sub">
            {[med.dosage, med.frequency].filter(Boolean).join(" · ") || "No dosage read"}
            {med.matched_generic_name && med.raw_name !== med.matched_generic_name && (
              <> · read as “{med.raw_name}”</>
            )}
          </p>
        </div>
        {worst === "critical" ? (
          <Badge variant="danger">Check with doctor</Badge>
        ) : worst === "warning" ? (
          <Badge variant="warning">Ask your doctor</Badge>
        ) : flags.length > 0 ? (
          <Badge variant="neutral">Note</Badge>
        ) : hasSafetyData ? (
          <Badge variant="success">No flags found</Badge>
        ) : (
          <Badge variant="neutral">Not checked</Badge>
        )}
      </header>

      {/* One plain-language verdict before the detail. A patient skimming five
          medicines should be able to tell from one line whether this is a
          "stop and ask" or a "fine, carry on". */}
      {verdict && (
        <p className={`med-review__verdict med-review__verdict--${worst}`}>{verdict}</p>
      )}

      <SafetyFlagList flags={flags} />

      {flags.length === 0 &&
        (hasSafetyData ? (
          <p className="med-review__clear">
            No conflicts found against your allergies, conditions, or the banned-medicine list. That is
            not a guarantee of safety — our medicine database is a limited sample.
          </p>
        ) : (
          /* The distinction that matters: we recognised the brand and can price
             it, but we hold no clinical data for it, so no check was run. Saying
             "no flags" here would be a false all-clear. */
          <p className="med-review__unchecked" role="status">
            We recognised this medicine and can compare prices for it, but it is not in our clinical
            database — we could <strong>not</strong> check it against your allergies, conditions, or
            pregnancy. Please confirm it with your doctor or pharmacist.
          </p>
        ))}

      {options.length > 0 ? (
        <div className="med-review__prices">
          <h4 className="med-review__prices-title">
            Price options
            {med.cheapest && costliest && med.cheapest.price_inr < costliest.price_inr && (
              <span className="med-review__save">
                {" "}
                save up to ₹{(costliest.price_inr - med.cheapest.price_inr).toFixed(2)}
              </span>
            )}
          </h4>
          <ul className="price-mini">
            {shown.map((o, i) => (
              <li
                key={i}
                className={`price-mini__row ${
                  med.cheapest?.product_name === o.product_name ? "price-mini__row--best" : ""
                }`}
              >
                <span className="price-mini__name">
                  {o.product_name}
                  {o.is_generic && <span className="price-mini__tag">generic</span>}
                </span>
                <span className="price-mini__meta">{o.unit}</span>
                <span className="price-mini__price">₹{o.price_inr.toFixed(2)}</span>
              </li>
            ))}
          </ul>
          {options.length > 3 && (
            <button
              type="button"
              className="btn-link"
              onClick={() => setShowAllPrices((v) => !v)}
            >
              {showAllPrices ? "Show fewer" : `Show all ${options.length} options`}
            </button>
          )}
          <p className="med-review__price-note">
            Informational only. Same composition can still differ in inactive ingredients — ask your
            pharmacist before switching brands.
          </p>
        </div>
      ) : (
        <p className="med-review__price-note">
          No price data for this medicine in our sample list yet.
        </p>
      )}
    </article>
  );
}
