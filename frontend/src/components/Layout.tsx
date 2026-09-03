import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useScrolled } from "../hooks/useScrolled";
import ReminderBanner from "./ReminderBanner";
import ProfileMenu from "./ProfileMenu";

// Day-to-day tasks only. Profile and the emergency card live in the account
// menu (ProfileMenu), the way Google Pay keeps profile/QR behind the avatar.
const NAV_ITEMS = [
  { to: "/", key: "dashboard" },
  { to: "/upload", key: "uploadPrescription" },
  { to: "/medications", key: "myMedications" },
  { to: "/chat", key: "chatbot" },
  { to: "/prices", key: "priceCompare" },
  { to: "/pharmacies", key: "pharmacies" },
  { to: "/wellness", key: "wellness" },
  { to: "/appointments", key: "appointments" },
];

export default function Layout() {
  const { t } = useTranslation();
  const location = useLocation();

  const [menuOpen, setMenuOpen] = useState(false);
  const scrolled = useScrolled();

  // Navigating on mobile should close the drawer, otherwise it stays open
  // over the page the user just asked for.
  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  return (
    <div className="app-shell">
      <header className={`topbar ${scrolled ? "is-scrolled" : ""}`}>
        <div className="brand">🩺 {t("appName")}</div>

        <button
          type="button"
          className="nav-toggle"
          onClick={() => setMenuOpen((o) => !o)}
          aria-expanded={menuOpen}
          aria-controls="primary-nav"
          aria-label={menuOpen ? "Close menu" : "Open menu"}
        >
          {menuOpen ? "✕" : "☰"}
        </button>

        <nav className={`nav ${menuOpen ? "is-open" : ""}`} id="primary-nav">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"}>
              {t(item.key)}
            </NavLink>
          ))}
        </nav>

        <div className="topbar-right">
          <ProfileMenu />
        </div>
      </header>

      <main className="content">
        <ReminderBanner />
        <Outlet />
      </main>
    </div>
  );
}
