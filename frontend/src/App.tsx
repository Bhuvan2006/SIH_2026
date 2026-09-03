import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";
import DoctorLayout from "./components/DoctorLayout";
import Login from "./pages/Login";
import Landing from "./pages/Landing";
import Dashboard from "./pages/Dashboard";
import Chatbot from "./pages/Chatbot";
import Profile from "./pages/Profile";
import UploadPrescription from "./pages/UploadPrescription";
import PriceCompare from "./pages/PriceCompare";
import Pharmacies from "./pages/Pharmacies";
import Wellness from "./pages/Wellness";
import BookAppointment from "./pages/BookAppointment";
import DoctorLogin from "./pages/DoctorLogin";
import DoctorDashboard from "./pages/DoctorDashboard";
import DoctorAppointments from "./pages/DoctorAppointments";
import DoctorPatientView from "./pages/DoctorPatientView";
import DoctorSchedule from "./pages/DoctorSchedule";
import DoctorProfile from "./pages/DoctorProfile";
import Medications from "./pages/Medications";
import Onboarding from "./pages/Onboarding";
import EmergencyCard from "./pages/EmergencyCard";
import PublicEmergency from "./pages/PublicEmergency";

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/welcome" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/emergency/:token" element={<PublicEmergency />} />

          <Route
            path="/onboarding"
            element={
              <ProtectedRoute>
                <Onboarding />
              </ProtectedRoute>
            }
          />

          {/* Doctor Public Route */}
          <Route path="/doctor/login" element={<DoctorLogin />} />

          {/* Doctor Protected Routes */}
          <Route
            path="/doctor"
            element={
              <ProtectedRoute requireRole="doctor">
                <DoctorLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<DoctorDashboard />} />
            <Route path="appointments" element={<DoctorAppointments />} />
            <Route path="schedule" element={<DoctorSchedule />} />
            <Route path="profile" element={<DoctorProfile />} />
            <Route path="patient/:id" element={<DoctorPatientView />} />
          </Route>

          {/* Patient Protected Routes */}
          <Route
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route path="/" element={<Dashboard />} />
            <Route path="/upload" element={<UploadPrescription />} />
            <Route path="/medications" element={<Medications />} />
            <Route path="/chat" element={<Chatbot />} />
            <Route path="/prices" element={<PriceCompare />} />
            <Route path="/pharmacies" element={<Pharmacies />} />
            <Route path="/wellness" element={<Wellness />} />
            <Route path="/profile" element={<Profile />} />
            <Route path="/emergency-card" element={<EmergencyCard />} />
            <Route path="/appointments" element={<BookAppointment />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
