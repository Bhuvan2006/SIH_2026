import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { Alert, Button, TextField } from "../components/ui";

export default function DoctorLogin() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { login } = useAuth();

  const [phone, setPhone] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [otp, setOtp] = useState("");
  const [devOtp, setDevOtp] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const requestOtp = async () => {
    setError(null);
    if (!phone.trim()) {
      setError("Enter a phone number");
      return;
    }
    setBusy(true);
    try {
      const res = await api.post("/auth/doctor/otp/request", { phone });
      setDevOtp(res.data.dev_otp ?? null);
      setOtpSent(true);
    } catch {
      setError("Could not send OTP. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const verifyOtp = async () => {
    setError(null);
    if (!otp.trim()) {
      setError("Enter the code you received");
      return;
    }
    setBusy(true);
    try {
      const res = await api.post("/auth/doctor/otp/verify", { phone, otp });
      // The role goes in with the token: the session loader needs it to call
      // /doctor/me rather than /patients/me, which rejects a doctor's token.
      await login(res.data.access_token, res.data.doctor_id, "doctor");
      navigate("/doctor");
    } catch {
      setError("Invalid or expired code. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-screen">
      <form
        className="login-card"
        onSubmit={(e) => {
          e.preventDefault();
          otpSent ? verifyOtp() : requestOtp();
        }}
      >
        <h1>👨‍⚕️ Doctor Login</h1>
        <p className="tagline">Sign in to manage your appointments</p>

        {!otpSent ? (
          <TextField
            label={t("phoneNumber")}
            type="tel"
            placeholder="+91XXXXXXXXXX"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            autoComplete="tel"
            required
          />
        ) : (
          <>
            <TextField
              label={t("enterOtp")}
              type="text"
              inputMode="numeric"
              maxLength={6}
              placeholder="000000"
              value={otp}
              onChange={(e) => setOtp(e.target.value)}
              helperText={t("otpHint")}
              autoComplete="one-time-code"
              required
            />
            {devOtp && <Alert variant="warning">Dev OTP: {devOtp}</Alert>}
          </>
        )}

        {error && <Alert variant="danger">{error}</Alert>}

        <Button type="submit" loading={busy} fullWidth>
          {otpSent ? t("verify") : t("sendOtp")}
        </Button>
      </form>
    </div>
  );
}
