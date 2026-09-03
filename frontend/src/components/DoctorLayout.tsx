import { NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import ProfileMenu from "./ProfileMenu";

const DOCTOR_NAV_ITEMS = [
  { to: "/doctor", key: "Dashboard" },
  { to: "/doctor/appointments", key: "Appointments" },
  { to: "/doctor/schedule", key: "My schedule" },
  { to: "/doctor/profile", key: "Profile" },
];

export default function DoctorLayout() {
  const { t } = useTranslation();
  // We can reuse ProfileMenu for logout, it just clears local storage.
  return (
    <div className="app-shell">
      <header className="topbar is-scrolled">
        <div className="brand">👨‍⚕️ {t("appName")} Doctor</div>

        <nav className="nav" id="primary-nav">
          {DOCTOR_NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/doctor"}>
              {item.key}
            </NavLink>
          ))}
        </nav>

        <div className="topbar-right">
          <ProfileMenu />
        </div>
      </header>

      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
