import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type Doctor, type Patient } from "../api/client";

export type Role = "patient" | "doctor";

const TOKEN_KEY = "arogya_token";
const ROLE_KEY = "arogya_role";
const USER_KEY = "arogya_user_id";

interface AuthContextValue {
  role: Role | null;
  patient: Patient | null;
  doctor: Doctor | null;
  loading: boolean;
  isAuthenticated: boolean;
  login: (token: string, userId: string, role?: Role) => Promise<void>;
  logout: () => void;
  refreshPatient: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

/**
 * Session state for both kinds of user.
 *
 * This used to load `/patients/me` unconditionally. A doctor's token is
 * rejected by that endpoint, so `patient` stayed null, `isAuthenticated` was
 * false, and ProtectedRoute bounced every signed-in doctor straight back to
 * the landing page — the doctor interface was unreachable.
 *
 * The role is stored alongside the token so a page reload knows which "me"
 * endpoint to call without having to guess or try both.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<Role | null>(
    () => (localStorage.getItem(ROLE_KEY) as Role | null) ?? null
  );
  const [patient, setPatient] = useState<Patient | null>(null);
  const [doctor, setDoctor] = useState<Doctor | null>(null);
  const [loading, setLoading] = useState(true);

  const loadSession = async (which: Role | null) => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
      setPatient(null);
      setDoctor(null);
      setLoading(false);
      return;
    }
    try {
      if (which === "doctor") {
        const res = await api.get<Doctor>("/doctor/me");
        setDoctor(res.data);
        setPatient(null);
      } else {
        const res = await api.get<Patient>("/patients/me");
        setPatient(res.data);
        setDoctor(null);
      }
    } catch {
      // A token that no longer works is worse than none: it leaves the app
      // half-signed-in. Clear it so the user lands on a login screen.
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(ROLE_KEY);
      localStorage.removeItem(USER_KEY);
      setPatient(null);
      setDoctor(null);
      setRole(null);
    } finally {
      setLoading(false);
    }
  };

  const refreshPatient = async () => {
    await loadSession((localStorage.getItem(ROLE_KEY) as Role | null) ?? "patient");
  };

  useEffect(() => {
    loadSession((localStorage.getItem(ROLE_KEY) as Role | null) ?? "patient");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = async (token: string, userId: string, nextRole: Role = "patient") => {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(ROLE_KEY, nextRole);
    localStorage.setItem(USER_KEY, userId);
    // Kept for anything still reading the old key.
    localStorage.setItem("arogya_patient_id", userId);
    setRole(nextRole);
    setLoading(true);
    await loadSession(nextRole);
  };

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(ROLE_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem("arogya_patient_id");
    setPatient(null);
    setDoctor(null);
    setRole(null);
  };

  return (
    <AuthContext.Provider
      value={{
        role,
        patient,
        doctor,
        loading,
        isAuthenticated: !!patient || !!doctor,
        login,
        logout,
        refreshPatient,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
