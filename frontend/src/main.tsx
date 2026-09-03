import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './components/ui/ui.css'
import './styles/landing.css'
import './styles/profile.css'
import './styles/safety.css'
import './styles/insights.css'
import './styles/wellness.css'
import './styles/markdown.css'
import './styles/appointments.css'
import './i18n'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
