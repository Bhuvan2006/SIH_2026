import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import type { EmergencyProfile } from "../api/client";
import { Alert, Spinner } from "../components/ui";
import EmergencyProfileView from "../components/EmergencyProfileView";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

/**
 * The page a QR scan lands on. Deliberately unauthenticated -- a paramedic
 * cannot be asked to log in -- so it uses a bare axios instance rather than
 * the app's client, whose interceptor would redirect to /login on 401.
 */
export default function PublicEmergency() {
  const { token } = useParams<{ token: string }>();
  const [profile, setProfile] = useState<EmergencyProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    axios
      .get<EmergencyProfile>(`${API_BASE_URL}/emergency/${token}`)
      .then((res) => setProfile(res.data))
      .catch(() =>
        setError("This emergency profile link is not valid, or it has been revoked by its owner.")
      )
      .finally(() => setLoading(false));
  }, [token]);

  return (
    <div className="emg-page">
      {loading ? (
        <div style={{ padding: 60, textAlign: "center" }}>
          <Spinner size="lg" label="Loading emergency information…" />
        </div>
      ) : error ? (
        <div style={{ maxWidth: 560, margin: "60px auto", padding: "0 20px" }}>
          <Alert variant="danger" title="Link not valid">
            {error}
          </Alert>
        </div>
      ) : (
        profile && <EmergencyProfileView profile={profile} />
      )}
    </div>
  );
}
