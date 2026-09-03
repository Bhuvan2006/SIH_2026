import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type PriceComparisonResponse } from "../api/client";
import { EmptyState } from "../components/ui";

interface DrugSearchResult {
  drug_id: string;
  generic_name: string;
  composition: string;
  brand_names?: string[];
  matched_brand?: string | null;
  has_prices?: boolean;
  /** False for bulk-catalogue results, which carry no clinical data. */
  has_safety_data?: boolean;
  prescription_required?: boolean | null;
}

export default function PriceCompare() {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<DrugSearchResult[]>([]);
  const [comparison, setComparison] = useState<PriceComparisonResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const [searched, setSearched] = useState(false);

  const handleSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setComparison(null);
    try {
      const res = await api.get<DrugSearchResult[]>("/prices/search", { params: { q: query } });
      setResults(res.data);
      setSearched(true);
    } finally {
      setLoading(false);
    }
  };

  const handleSelect = async (drugId: string) => {
    setLoading(true);
    try {
      const res = await api.get<PriceComparisonResponse>(`/prices/by-drug/${drugId}`);
      setComparison(res.data);
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h1>{t("priceCompare")}</h1>
      <div className="search-row">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("searchDrug")}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
        />
        <button className="btn-primary" onClick={handleSearch} disabled={loading}>
          Search
        </button>
      </div>

      {results.length > 0 && (
        <ul className="search-results">
          {results.map((r) => (
            <li key={r.drug_id} onClick={() => handleSelect(r.drug_id)}>
              {/* When the patient searched a brand ("Dolo"), lead with that
                  brand and show the generic it maps to -- otherwise the result
                  looks like it ignored what they typed. */}
              {/* For a catalogue product the generic name IS its composition
                  and its only "brand" is the product itself, so printing all
                  three fields repeated the same text three times. Show each
                  fact once. */}
              {r.matched_brand ? (
                <>
                  <strong>{r.matched_brand}</strong>
                  {r.generic_name !== r.composition && r.generic_name !== r.matched_brand && (
                    <span className="composition-line"> → {r.generic_name}</span>
                  )}
                </>
              ) : (
                <strong>{r.generic_name}</strong>
              )}
              {r.composition !== r.matched_brand && (
                <div className="composition-line">{r.composition}</div>
              )}
              {(() => {
                const others = (r.brand_names ?? []).filter((b) => b !== r.matched_brand);
                return others.length > 0 ? (
                  <div className="brand-line">Also sold as: {others.join(", ")}</div>
                ) : null;
              })()}
              {r.has_safety_data === false && (
                <div className="brand-line">
                  Price data only — not in our clinical database, so no allergy or pregnancy check.
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {searched && !loading && results.length === 0 && !comparison && (
        <EmptyState
          icon="🔍"
          title={`No medicine matching "${query}"`}
          description="Try the generic name (e.g. Paracetamol) or the brand printed on the strip (e.g. Dolo 650). Our price list covers commonly prescribed medicines and is still growing."
        />
      )}

      {comparison && (
        <div className="price-comparison">
          <h2>{comparison.generic_name}</h2>
          <p className="composition-line">
            {t("composition")}: {comparison.composition}
          </p>
          {/* Six columns will not fit a phone. Rather than scroll sideways,
              the same markup restacks into one card per product under 700px
              (see .price-table in profile.css); data-label carries the column
              name so each value stays self-describing once headers are gone. */}
          <div className="table-scroll">
            <table className="price-table price-table--responsive">
              <thead>
                <tr>
                  <th>Product</th>
                  <th>Manufacturer</th>
                  <th>Type</th>
                  <th>Price (₹)</th>
                  <th>Unit</th>
                  <th>Savings</th>
                </tr>
              </thead>
              <tbody>
                {comparison.options.map((o, i) => (
                  <tr
                    key={i}
                    className={comparison.cheapest?.product_name === o.product_name ? "cheapest-row" : ""}
                  >
                    <td data-label="Product">
                      {o.product_name}
                      {comparison.cheapest?.product_name === o.product_name && (
                        <span className="badge-cheapest"> ★ {t("cheapestOption")}</span>
                      )}
                    </td>
                    <td data-label="Manufacturer">{o.manufacturer}</td>
                    <td data-label="Type">
                      {o.is_generic ? "Generic" : "Branded"}
                      {/* Only rendered when we actually know. A missing flag
                          means unrecorded, which must not be shown as OTC. */}
                      {o.prescription_required === true && (
                        <span className="rx-tag" title="Prescription required"> · Rx</span>
                      )}
                      {o.prescription_required === false && (
                        <span className="otc-tag"> · OTC</span>
                      )}
                    </td>
                    <td data-label="Price">₹{o.price_inr.toFixed(2)}</td>
                    <td data-label="Unit">{o.unit}</td>
                    <td data-label="Savings">
                      {o.savings_pct_vs_costliest ? `${o.savings_pct_vs_costliest}% ${t("savings")}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="disclaimer-box">{comparison.disclaimer}</p>
        </div>
      )}
    </div>
  );
}
