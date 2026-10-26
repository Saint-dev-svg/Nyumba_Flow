import { useEffect, useRef, useState } from 'react'
import { AuthProvider } from './auth/AuthContext.jsx'
import { useAuth } from './auth/useAuth.js'
import './App.css'

function LoginScreen() {
  const { isLoading, sessionError, login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [formError, setFormError] = useState('')

  async function handleSubmit(event) {
    event.preventDefault()
    setFormError('')

    const normalizedEmail = email.trim()
    if (!normalizedEmail || !password) {
      setFormError('Enter your email address and password.')
      return
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) {
      setFormError('Enter a valid email address.')
      return
    }

    setIsSubmitting(true)
    try {
      await login(normalizedEmail, password)
    } catch (error) {
      setFormError(error.message || 'Unable to sign in. Please try again.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="page-shell">
      <header className="site-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">N</span>
          <span>NyumbaFlow</span>
        </div>
        <span className="header-note">Property management</span>
      </header>

      <section className="login-layout" aria-labelledby="page-title">
        <div className="welcome-panel">
          <p className="eyebrow">A clearer way to manage</p>
          <h1 id="page-title">Your properties,<br />in good order.</h1>
          <p className="welcome-copy">
            Keep the day-to-day details of your properties, tenants and rent in one place.
          </p>
          <div className="welcome-rule" />
          <p className="welcome-footnote">Thoughtful tools for the work of managing homes.</p>
        </div>

        <div className="form-panel">
          {isLoading ? (
            <div className="loading-state" role="status" aria-live="polite">
              <span className="loading-dot" aria-hidden="true" />
              Checking your session…
            </div>
          ) : (
            <>
              <div className="form-heading">
                <p className="eyebrow">Landlord access</p>
                <h2 id="login-heading">Sign in to continue</h2>
                <p className="form-intro">Enter your account details to access your workspace.</p>
              </div>

              {(sessionError || formError) && (
                <div className="form-error" role="alert">
                  {formError || sessionError}
                </div>
              )}

              <form onSubmit={handleSubmit} noValidate aria-labelledby="login-heading">
                <div className="field-group">
                  <label htmlFor="email">Email address</label>
                  <input
                    id="email"
                    name="email"
                    type="email"
                    autoComplete="username"
                    inputMode="email"
                    autoCapitalize="none"
                    spellCheck="false"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    disabled={isSubmitting}
                    required
                  />
                </div>

                <div className="field-group">
                  <label htmlFor="password">Password</label>
                  <div className="password-wrap">
                    <input
                      id="password"
                      name="password"
                      type={showPassword ? 'text' : 'password'}
                      autoComplete="current-password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      disabled={isSubmitting}
                      required
                    />
                    <button
                      className="visibility-button"
                      type="button"
                      aria-pressed={showPassword}
                      onClick={() => setShowPassword((visible) => !visible)}
                    >
                      {showPassword ? 'Hide' : 'Show'}
                    </button>
                  </div>
                </div>

                <button className="primary-button" type="submit" disabled={isSubmitting}>
                  {isSubmitting ? 'Signing in…' : 'Sign in'}
                </button>
              </form>

              <p className="form-note">Your account details are used only to sign in.</p>
            </>
          )}
        </div>
      </section>

      <footer className="site-footer">
        <span>NyumbaFlow</span>
        <span>Property management, made practical.</span>
      </footer>
    </main>
  )
}

const navigationItems = [
  { label: 'Overview', available: true },
  { label: 'Properties', available: false },
  { label: 'Tenants', available: false },
  { label: 'Leases', available: false },
  { label: 'Invoices', available: false },
  { label: 'Payments', available: false },
]

function DashboardShell({ user }) {
  const { logout } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuButtonRef = useRef(null)
  const overviewRef = useRef(null)

  useEffect(() => {
    if (!menuOpen) return undefined

    overviewRef.current?.focus()
    function handleKeyDown(event) {
      if (event.key === 'Escape') {
        setMenuOpen(false)
        menuButtonRef.current?.focus()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [menuOpen])

  function selectOverview() {
    setMenuOpen(false)
    if (window.matchMedia('(max-width: 760px)').matches) {
      menuButtonRef.current?.focus()
    }
  }

  return (
    <div className="dashboard-shell">
      {menuOpen && (
        <button
          className="sidebar-backdrop"
          type="button"
          aria-label="Close navigation menu"
          onClick={() => setMenuOpen(false)}
        />
      )}
      <aside className={`app-sidebar${menuOpen ? ' is-open' : ''}`} aria-label="Main navigation">
        <a className="brand sidebar-brand" href="#overview" onClick={selectOverview}>
          <span className="brand-mark" aria-hidden="true">N</span>
          <span>NyumbaFlow</span>
        </a>
        <p className="sidebar-label">Workspace</p>
        <nav id="workspace-navigation" aria-label="Workspace">
          {navigationItems.map((item) => item.available ? (
            <button
              className="nav-item is-active"
              type="button"
              key={item.label}
              aria-current="page"
              ref={overviewRef}
              onClick={selectOverview}
            >
              <span className="nav-indicator" aria-hidden="true" />
              {item.label}
            </button>
          ) : (
            <div className="nav-item is-unavailable" key={item.label} aria-disabled="true">
              <span className="nav-indicator" aria-hidden="true" />
              <span>{item.label}</span>
              <span className="nav-status">Soon</span>
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">Property management</div>
      </aside>

      <div className="dashboard-main">
        <header className="dashboard-header">
          <div className="header-title-group">
            <button
              className="menu-button"
              type="button"
              ref={menuButtonRef}
              aria-label={menuOpen ? 'Close navigation menu' : 'Open navigation menu'}
              aria-expanded={menuOpen}
              aria-controls="workspace-navigation"
              onClick={() => setMenuOpen((open) => !open)}
            >
              <span aria-hidden="true">{menuOpen ? '×' : '☰'}</span>
            </button>
            <h1>Overview</h1>
          </div>
          <div className="account-controls">
            <div className="account-identity">
              <span className="account-name">{user.full_name || user.email}</span>
              {user.full_name && <span className="account-email">{user.email}</span>}
            </div>
            <button className="logout-button" type="button" onClick={logout}>Sign out</button>
          </div>
        </header>

        <main id="overview" className="overview-content">
          <section className="overview-intro" aria-labelledby="welcome-heading">
            <p className="eyebrow">Your workspace</p>
            <h2 id="welcome-heading">Welcome{user.full_name ? `, ${user.full_name.split(' ')[0]}` : ''}.</h2>
            <p>Manage your properties and keep the important details of your rental business in view.</p>
          </section>
          <section className="overview-empty" aria-labelledby="empty-heading">
            <div className="empty-icon" aria-hidden="true">
              <svg viewBox="0 0 40 40" fill="none">
                <path d="M7 18.5 20 8l13 10.5V32H7V18.5Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
                <path d="M16 32V22h8v10M12 19h.01M28 19h.01" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
              </svg>
            </div>
            <h3 id="empty-heading">Your overview will take shape here</h3>
            <p>Property and financial summaries will appear here after you add properties and records.</p>
          </section>
        </main>
      </div>
    </div>
  )
}

function AuthenticatedApp() {
  const { user } = useAuth()
  return user ? <DashboardShell user={user} /> : <LoginScreen />
}

function App() {
  return (
    <AuthProvider>
      <AuthenticatedApp />
    </AuthProvider>
  )
}

export default App
