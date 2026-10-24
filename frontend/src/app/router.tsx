import { Route, Routes } from 'react-router-dom'
import { Layout } from '../components/Layout'
import { RequireRole } from '../features/auth/RequireRole'
import LandingPage from '../pages/LandingPage'
import LoginPage from '../pages/LoginPage'
import RegisterPage from '../pages/RegisterPage'
import CustomerDashboardPage from '../pages/CustomerDashboardPage'
import VerificationPage from '../pages/VerificationPage'
import OfficerDashboardPage from '../pages/OfficerDashboardPage'
import SessionDetailsPage from '../pages/SessionDetailsPage'
import EvidencePage from '../pages/EvidencePage'
import SessionReportPage from '../pages/SessionReportPage'
import NotFoundPage from '../pages/NotFoundPage'
import DeveloperLabPage from '../pages/DeveloperLabPage'
export function AppRoutes() {
  return (
    <Routes><Route element={<Layout />}>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route element={<RequireRole role="customer" />}>
        <Route path="/dashboard" element={<CustomerDashboardPage />} />
        <Route path="/verify" element={<VerificationPage />} />
      </Route>
      <Route element={<RequireRole role="officer" />}>
        <Route path="/officer" element={<OfficerDashboardPage />} />
        <Route path="/sessions/:sessionId" element={<SessionDetailsPage />} />
        <Route path="/sessions/:sessionId/report" element={<SessionReportPage />} />
        <Route path="/sessions/:sessionId/evidence" element={<EvidencePage />} />
      </Route>
      {/* Developer accounts only (provisioned by an administrator). The backend checks the role on every developer API call too. */}
      <Route element={<RequireRole role="developer" />}>
        <Route path="/developer" element={<DeveloperLabPage />} />
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Route></Routes>
  )
}
