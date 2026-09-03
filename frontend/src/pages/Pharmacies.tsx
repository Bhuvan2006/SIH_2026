import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type Pharmacy } from "../api/client";

// Bengaluru center — matches the bundled mock pharmacy dataset used when
// PLACES_PROVIDER=mock (the default). Falls back to this if the browser
// denies/lacks geolocation.
const FALLBACK_COORDS = { lat: 12.9716, lon: 77.5946 };

export default function Pharmacies() {
  const { t } = useTranslation();
  const [pharmacies, setPharmacies] = useState<Pharmacy[]>([]);
  const [loading, setLoading] = useState(false);
  const [usedFallback, setUsedFallback] = useState(false);

  const fetchNearby = (lat: number, lon: number) => {
    setLoading(true);
    api
      .get<Pharmacy[]>("/pharmacies/nearby", { params: { lat, lon, radius_km: 10, limit: 15 } })
      .then((res) => setPharmacies(res.data))
      .finally(() => setLoading(false));
  };

  const handleFindNearby = () => {
    if (!navigator.geolocation) {
      setUsedFallback(true);
      fetchNearby(FALLBACK_COORDS.lat, FALLBACK_COORDS.lon);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setUsedFallback(false);
        fetchNearby(pos.coords.latitude, pos.coords.longitude);
      },
      () => {
        setUsedFallback(true);
        fetchNearby(FALLBACK_COORDS.lat, FALLBACK_COORDS.lon);
      }
    );
  };

  return (
    <div>
      <h1>{t("pharmacies")}</h1>
      <button className="btn-primary" onClick={handleFindNearby} disabled={loading}>
        📍 {t("findPharmacies")}
      </button>
      {usedFallback && (
        <p className="hint">Using a sample location (Bengaluru) — location access wasn't available.</p>
      )}

      {pharmacies.length > 0 && (
        <>
          <p className="hint">
            Nearby pharmacies from a sample directory — not a live stock check. Call ahead to confirm
            availability.
          </p>
          <ul className="pharmacy-list">
            {pharmacies.map((p) => (
              <li key={p.id} className="pharmacy-item">
                <div className="pharmacy-name">{p.name}</div>
                <div className="pharmacy-address">{p.address}</div>
                <div className="pharmacy-meta">
                  {p.distance_km != null && <span>{p.distance_km} km away</span>}
                  {p.phone && (
                    <a href={`tel:${p.phone}`} className="btn-link">
                      📞 {p.phone}
                    </a>
                  )}
                  <a
                    className="btn-link"
                    target="_blank"
                    rel="noreferrer"
                    href={`https://www.google.com/maps/search/?api=1&query=${p.latitude},${p.longitude}`}
                  >
                    🧭 Directions
                  </a>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
