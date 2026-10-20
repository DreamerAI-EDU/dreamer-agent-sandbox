import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router'
import './index.css'
import { LanguageProvider } from './lib/i18n'
import { RootGate } from './components/RootGate'
import { LoginPage } from './pages/LoginPage'
import { ForgotPasswordPage } from './pages/ForgotPasswordPage'
import { ResetPasswordPage } from './pages/ResetPasswordPage'
import { ConsentPage } from './pages/ConsentPage'
import { InvitePage } from './pages/InvitePage'
import { ParentHomePage } from './pages/ParentHomePage'
import { ParentDashboard } from './pages/ParentDashboard'
import { SafetyPage } from './pages/SafetyPage'
import { TeacherDashboard } from './pages/TeacherDashboard'
import { TeacherRegisterPage } from './pages/TeacherRegisterPage'
import { TeacherScoresPage } from './pages/teacher/TeacherScoresPage'
import { TeacherGeneratePage } from './pages/teacher/TeacherGeneratePage'
import { TeacherReportsPage } from './pages/teacher/TeacherReportsPage'
import { TeacherReportReviewPage } from './pages/teacher/TeacherReportReviewPage'
import { TeacherCrosswalkPage } from './pages/teacher/TeacherCrosswalkPage'
import { ParentReportsPage } from './pages/parent/ParentReportsPage'
import { ParentReportDetailPage } from './pages/parent/ParentReportDetailPage'
import ChatPage from './pages/ChatPage'
import KidPortfolioPage from './pages/KidPortfolioPage'
import { StudentLoginPage } from './pages/StudentLoginPage'
import { StudentHomePage } from './pages/StudentHomePage'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <LanguageProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/forgot" element={<ForgotPasswordPage />} />
          <Route path="/reset" element={<ResetPasswordPage />} />
          <Route path="/invite/:token" element={<InvitePage />} />
          <Route path="/consent" element={<ConsentPage />} />
          <Route path="/home" element={<ParentHomePage />} />
          <Route path="/parent" element={<ParentDashboard />} />
          <Route path="/safety" element={<SafetyPage />} />
          <Route path="/teacher" element={<TeacherDashboard />} />
          <Route path="/teacher/register" element={<TeacherRegisterPage />} />
          {/* PR-5 A1-A6 — teacher report console */}
          <Route path="/teacher/scores" element={<TeacherScoresPage />} />
          <Route path="/teacher/generate" element={<TeacherGeneratePage />} />
          <Route path="/teacher/reports" element={<TeacherReportsPage />} />
          <Route path="/teacher/reports/:reportId" element={<TeacherReportReviewPage />} />
          <Route path="/teacher/crosswalk" element={<TeacherCrosswalkPage />} />
          {/* PR-5 B1-B5 — parent read-only report views */}
          <Route path="/parent/reports" element={<ParentReportsPage />} />
          <Route path="/parent/reports/:reportId" element={<ParentReportDetailPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/portfolio" element={<KidPortfolioPage />} />
          {/* Bridge-3d — student self-login (join code + PIN) */}
          <Route path="/student/login" element={<StudentLoginPage />} />
          <Route path="/student" element={<StudentHomePage />} />
          <Route path="*" element={<RootGate />} />
        </Routes>
      </LanguageProvider>
    </BrowserRouter>
  </StrictMode>,
)
