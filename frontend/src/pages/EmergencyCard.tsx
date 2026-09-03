import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type EmergencyProfile } from "../api/client";
import { Alert, Button, Card, Spinner } from "../components/ui";
import EmergencyProfileView from "../components/EmergencyProfileView";

interface QrResponse {
  url: string;
  qr_data_uri: string | null;
}

export default function EmergencyCard() {
  const [qr, setQr] = useState<QrResponse | null>(null);
  const [profile, setProfile] = useState<EmergencyProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [copied, setCopied] = useState(false);

  const load = () =>
    Promise.all([api.get<QrResponse>("/emergency/qr"), api.get<EmergencyProfile>("/emergency/me")])
      .then(([q, p]) => {
        setQr(q.data);
        setProfile(p.data);
      })
      .finally(() => setLoading(false));

  useEffect(() => {
    load();
  }, []);

  const regenerate = async () => {
    if (
      !window.confirm(
        "Create a new QR code? Any card or printout you've already shared will stop working."
      )
    )
      return;
    setRegenerating(true);
    try {
      await api.post("/emergency/qr/regenerate");
      await load();
    } finally {
      setRegenerating(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: "center" }}>
        <Spinner size="lg" label="Building your emergency card…" />
      </div>
    );
  }

  return (
    <div>
      <div className="dash-hero animate-in">
        <h1>Emergency QR card</h1>
        <p>
          Print this or keep it on your phone&rsquo;s lock screen. Anyone who scans it sees your
          critical medical details — no login needed, so it works when you can&rsquo;t speak for
          yourself.
        </p>
      </div>

      <div className="qr-layout">
        <Card className="qr-card">
          {qr?.qr_data_uri ? (
            <img src={qr.qr_data_uri} alt="Your emergency medical QR code" className="qr-image" />
          ) : (
            <Alert variant="warning">QR image unavailable — use the link below instead.</Alert>
          )}

          <div className="qr-actions">
            <Button onClick={() => window.print()}>Print card</Button>
            <Button
              variant="ghost"
              onClick={() => {
                if (qr?.url) {
                  navigator.clipboard?.writeText(qr.url);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 2000);
                }
              }}
            >
              {copied ? "Copied ✓" : "Copy link"}
            </Button>
            <Button variant="ghost" loading={regenerating} onClick={regenerate}>
              Regenerate
            </Button>
          </div>

          {qr?.url && (
            <p className="qr-url">
              <a href={qr.url} target="_blank" rel="noreferrer">
                {qr.url}
              </a>
            </p>
          )}
        </Card>

        <div className="qr-preview">
          <h2 className="section-heading-simple">What a responder sees</h2>
          {profile && <EmergencyProfileView profile={profile} />}
        </div>
      </div>

      <Alert variant="warning" className="no-print">
        <strong>Before you share this:</strong> anyone who scans the code — or photographs it — can
        read this page without a password. That is deliberate, so it works in an emergency. Only put
        details on it you accept a stranger could read, and use <em>Regenerate</em> if a card is
        ever lost. You can edit what appears here from your{" "}
        <Link to="/profile">health profile</Link>.
      </Alert>
    </div>
  );
}
