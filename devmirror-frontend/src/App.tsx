import { Component, ReactNode, ErrorInfo, lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'

const Landing      = lazy(() => import('./pages/Landing'))
const Dashboard    = lazy(() => import('./pages/Dashboard'))
const Gmail        = lazy(() => import('./pages/Gmail'))
const YouTube      = lazy(() => import('./pages/YouTube'))
const Coach        = lazy(() => import('./pages/Coach'))
const GrowthReport = lazy(() => import('./pages/GrowthReport'))
const DSAProgress  = lazy(() => import('./pages/DSAProgress'))
const FocusToday   = lazy(() => import('./pages/FocusToday'))
const LearnVsBuild = lazy(() => import('./pages/LearnVsBuild'))
const Internship   = lazy(() => import('./pages/Internship'))
const Calendar     = lazy(() => import('./pages/Calendar'))

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null }
  componentDidCatch(error: Error, _info: ErrorInfo) { this.setState({ error }) }
  static getDerivedStateFromError(error: Error) { return { error } }
  render() {
    if (this.state.error) {
      return (
        <div style={{ background: '#0A0A0F', color: '#EF4444', fontFamily: 'monospace', padding: '2rem', minHeight: '100vh' }}>
          <h2 style={{ color: '#F59E0B', marginBottom: '1rem' }}>Runtime Error</h2>
          <pre style={{ whiteSpace: 'pre-wrap', fontSize: '13px' }}>{String(this.state.error)}</pre>
          <pre style={{ whiteSpace: 'pre-wrap', fontSize: '11px', color: '#6B7280', marginTop: '1rem' }}>
            {(this.state.error as Error).stack}
          </pre>
        </div>
      )
    }
    return this.props.children
  }
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Suspense fallback={<div style={{ background: '#0A0A0F', minHeight: '100vh' }} />}>
          <Routes>
            {/* Public */}
            <Route path="/"      element={<Landing />} />
            <Route path="/login" element={<Navigate to="/dashboard" replace />} />

            {/* Core workspace */}
            <Route path="/dashboard"   element={<Dashboard />} />
            <Route path="/gmail"       element={<Gmail />} />
            <Route path="/youtube"     element={<YouTube />} />
            <Route path="/calendar"    element={<Calendar />} />
            <Route path="/coach"       element={<Coach />} />

            {/* Legacy analytics pages */}
            <Route path="/growth-report"  element={<GrowthReport />} />
            <Route path="/dsa"            element={<DSAProgress />} />
            <Route path="/focus"          element={<FocusToday />} />
            <Route path="/learn-vs-build" element={<LearnVsBuild />} />
            <Route path="/internship"     element={<Internship />} />

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
