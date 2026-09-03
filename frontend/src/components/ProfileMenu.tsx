import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";
import { SUPPORTED_LANGUAGES } from "../i18n";

function initialsFor(name: string | null | undefined, phone: string): string {
  if (name && name.trim()) {
    const parts = name.trim().split(/\s+/);
    return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase();
  }
  // Fall back to the last two digits of the phone so the avatar is still
  // recognisably "theirs" before they've filled in a name.
  return phone.replace(/\D/g, "").slice(-2) || "?";
}

/**
 * Account avatar + dropdown, in the pattern people already know from Google
 * Pay / Google apps: a circular avatar top-right that opens a sheet with the
 * account identity, profile, emergency QR, language, and sign-out.
 *
 * Keeping these out of the main navigation matters -- profile and emergency
 * card are account settings, not day-to-day features, and crowding them into
 * the nav bar pushed the actual daily tasks (reminders, prescriptions) aside.
 */
export default function ProfileMenu() {
  const { patient, logout } = useAuth();
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Close on outside click and on Escape -- expected behaviour for a menu,
  // and required so keyboard users aren't trapped in it.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const go = (path: string) => {
    setOpen(false);
    navigate(path);
  };

  const changeLanguage = async (lang: string) => {
    i18n.changeLanguage(lang);
    localStorage.setItem("arogya_lang", lang);
    try {
      await api.patch("/patients/me", { preferred_language: lang });
    } catch {
      // Non-fatal: the UI language still switches locally.
    }
  };

  if (!patient) return null;

  return (
    <div className="pm" ref={wrapRef}>
      <button
        type="button"
        className="pm__avatar"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label="Account and settings"
      >
        {initialsFor(patient.name, patient.phone)}
      </button>

      {open && (
        <div className="pm__sheet" role="menu">
          <div className="pm__identity">
            <div className="pm__avatar pm__avatar--lg" aria-hidden="true">
              {initialsFor(patient.name, patient.phone)}
            </div>
            <div className="pm__identity-text">
              <p className="pm__name">{patient.name || "Add your name"}</p>
              <p className="pm__phone">{patient.phone}</p>
              {patient.blood_group && <span className="pm__blood">{patient.blood_group}</span>}
            </div>
          </div>

          <div className="pm__actions">
            <button type="button" className="pm__item" role="menuitem" onClick={() => go("/profile")}>
              <span className="pm__item-icon" aria-hidden="true">
                👤
              </span>
              <span>
                <strong>{t("profile")}</strong>
                <em>Blood group, allergies, contacts</em>
              </span>
            </button>

            <button
              type="button"
              className="pm__item"
              role="menuitem"
              onClick={() => go("/emergency-card")}
            >
              <span className="pm__item-icon" aria-hidden="true">
                🔳
              </span>
              <span>
                <strong>{t("emergencyCard")}</strong>
                <em>Your scannable medical QR</em>
              </span>
            </button>
          </div>

          <div className="pm__section">
            <label className="pm__label" htmlFor="pm-lang">
              {t("language")}
            </label>
            <select
              id="pm-lang"
              className="ui-field__input"
              value={i18n.language}
              onChange={(e) => changeLanguage(e.target.value)}
            >
              {Object.entries(SUPPORTED_LANGUAGES).map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </select>
          </div>

          <button
            type="button"
            className="pm__item pm__item--danger"
            role="menuitem"
            onClick={() => {
              logout();
              navigate("/login");
            }}
          >
            <span className="pm__item-icon" aria-hidden="true">
              ↪
            </span>
            <span>
              <strong>{t("logout")}</strong>
            </span>
          </button>
        </div>
      )}
    </div>
  );
}
