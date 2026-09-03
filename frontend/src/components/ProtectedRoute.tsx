import { Navigate, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth, type Role } from "../context/AuthContext";
import { Spinner } from "./ui";

/**
 * Route guard for both roles.
 *
 * `requireRole` matters as much as the sign-in check: without it a signed-in
 * doctor could open the patient app (and vice versa) and every request on the
 * page would fail with 401s that look like the app is broken. Sending them to
 * their own home instead is both clearer and the access boundary.
 */
export default function ProtectedRoute({
  children,
  requireRole = "patient",
}: {
  children: ReactNode;
  requireRole?: Role;
}) {
  const { isAuthenticated, role, patient, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="page-loading">
        <Spinner size="lg" label="Loading your account…" />
      </div>
    );
  }

  // Send signed-out visitors to the landing page rather than straight to a
  // bare login form -- they get to see what the product does first.
  if (!isAuthenticated) {
    return <Navigate to={requireRole === "doctor" ? "/doctor/login" : "/welcome"} replace />;
  }

  if (role !== requireRole) {
    return <Navigate to={role === "doctor" ? "/doctor" : "/"} replace />;
  }

  // Registered but hasn't completed setup: hold them at onboarding. The
  // emergency QR, personalised answers, and reminders are all empty shells
  // without this data, so it's collected before the app proper.
  if (
    requireRole === "patient" &&
    patient &&
    !patient.profile_completed &&
    location.pathname !== "/onboarding"
  ) {
    return <Navigate to="/onboarding" replace />;
  }

  return <>{children}</>;
}
