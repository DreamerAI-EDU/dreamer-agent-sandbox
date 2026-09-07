import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router'
import './index.css'
import { LanguageProvider } from './lib/i18n'
import { RootGate } from './components/RootGate'
import { LoginPage } from './pages/LoginPage'
import { ConsentPage } from './pages/ConsentPage'
import { InvitePage } from './pages/InvitePage'
import { ParentHomePage } from './pages/ParentHomePage'
import { ParentDashboard } from './pages/ParentDashboard'
import { SafetyPage } from './pages/SafetyPage'
import { TeacherDashboard } from './pages/TeacherDashboard'
import { TeacherRegisterPage } from './pages/TeacherRegisterPage'
import ChatPage from './pages/ChatPage'
import KidPortfolioPage from './pages/KidPortfolioPage'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <LanguageProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/invite/:token" element={<InvitePage />} />
          <Route path="/consent" element={<ConsentPage />} />
          <Route path="/home" element={<ParentHomePage />} />
          <Route path="/parent" element={<ParentDashboard />} />
          <Route path="/safety" element={<SafetyPage />} />
          <Route path="/teacher" element={<TeacherDashboard />} />
          <Route path="/teacher/register" element={<TeacherRegisterPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/portfolio" element={<KidPortfolioPage />} />
          <Route path="*" element={<RootGate />} />
        </Routes>
      </LanguageProvider>
    </BrowserRouter>
  </StrictMode>,
)
