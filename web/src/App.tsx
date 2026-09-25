import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth'
import { Shell } from './components/Shell'
import { AgentBuilder } from './pages/AgentBuilder'
import { AgentsPage } from './pages/AgentsPage'
import { CallDetailPage, CallsPage } from './pages/CallsPage'
import { CampaignDetailPage, CampaignsPage } from './pages/CampaignsPage'
import { Dashboard } from './pages/Dashboard'
import { LandingPage } from './pages/LandingPage'
import { WallboardPage } from './pages/WallboardPage'
import { ToastProvider } from './toast'

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            {/* Creative Award-Level Landing Page */}
            <Route path="/" element={<LandingPage />} />

            {/* Application Console & Fleet Dashboard */}
            <Route element={<Shell />}>
              <Route path="overview" element={<Dashboard />} />
              <Route path="wallboard" element={<WallboardPage />} />
              <Route path="campaigns" element={<CampaignsPage />} />
              <Route path="campaigns/:id" element={<CampaignDetailPage />} />
              <Route path="agents" element={<AgentsPage />} />
              <Route path="agents/new" element={<AgentBuilder />} />
              <Route path="agents/:id" element={<AgentBuilder />} />
              <Route path="calls" element={<CallsPage />} />
              <Route path="calls/:id" element={<CallDetailPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ToastProvider>
  )
}

