import { useEffect, useRef, useState } from 'react'
import { AuthProvider } from './auth/AuthContext.jsx'
import { useAuth } from './auth/useAuth.js'
import { apiRequest } from './api/client.js'
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
  { label: 'Properties', available: true },
  { label: 'Tenants', available: false },
  { label: 'Leases', available: false },
  { label: 'Invoices', available: false },
  { label: 'Payments', available: false },
]

function PropertyOverview({ refreshKey }) {
  const [overview, setOverview] = useState({ loading: true, properties: [], error: '' })
  const [retryCount, setRetryCount] = useState(0)

  useEffect(() => {
    let isCurrent = true

    async function fetchOverview() {
      setOverview((current) => ({ ...current, loading: true, error: '' }))
      try {
        const result = await apiRequest('/api/properties', { authenticated: true })
        if (!Array.isArray(result?.properties)) {
          throw new Error('The property list could not be read. Please try again.')
        }

        const properties = await Promise.all(result.properties.map(async (property) => {
          try {
            const unitResult = await apiRequest(
              `/api/properties/${encodeURIComponent(property.id)}/units`,
              { authenticated: true },
            )
            if (!Array.isArray(unitResult?.units)) {
              throw new Error('The unit list could not be read.')
            }
            return { ...property, unitCount: unitResult.units.length, unitError: '' }
          } catch (error) {
            return { ...property, unitCount: null, unitError: error.message }
          }
        }))

        if (isCurrent) setOverview({ loading: false, properties, error: '' })
      } catch (error) {
        if (isCurrent) {
          setOverview({
            loading: false,
            properties: [],
            error: error.message || 'Unable to load properties. Please try again.',
          })
        }
      }
    }

    fetchOverview()
    return () => {
      isCurrent = false
    }
  }, [retryCount, refreshKey])

  const hasUnitFailures = overview.properties.some((property) => property.unitError)

  return (
    <section className="property-overview" aria-labelledby="properties-heading">
      <div className="property-section-heading">
        <div>
          <p className="eyebrow">Your portfolio</p>
          <h3 id="properties-heading">Properties</h3>
        </div>
        {!overview.loading && overview.properties.length > 0 && (
          <span className="property-total">
            {overview.properties.length} {overview.properties.length === 1 ? 'property' : 'properties'}
          </span>
        )}
      </div>

      {overview.loading ? (
        <div className="overview-message" role="status" aria-live="polite">
          <span className="loading-dot" aria-hidden="true" />
          Loading your properties and units…
        </div>
      ) : overview.error ? (
        <div className="overview-message overview-error" role="alert">
          <div>
            <h4>Properties could not be loaded</h4>
            <p>{overview.error}</p>
          </div>
          <button className="retry-button" type="button" onClick={() => setRetryCount((count) => count + 1)}>
            Try again
          </button>
        </div>
      ) : overview.properties.length === 0 ? (
        <div className="overview-empty" aria-labelledby="empty-heading">
          <div className="empty-icon" aria-hidden="true">
            <svg viewBox="0 0 40 40" fill="none">
              <path d="M7 18.5 20 8l13 10.5V32H7V18.5Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
              <path d="M16 32V22h8v10M12 19h.01M28 19h.01" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
          </div>
          <h4 id="empty-heading">No properties yet</h4>
          <p>Your property list will appear here once properties have been added to your account.</p>
        </div>
      ) : (
        <>
          {hasUnitFailures && (
            <div className="partial-error" role="alert">
              <p>Some unit counts could not be loaded, so the overview is incomplete.</p>
              <button className="retry-button" type="button" onClick={() => setRetryCount((count) => count + 1)}>
                Retry loading
              </button>
            </div>
          )}
          <ul className="property-list">
            {overview.properties.map((property) => (
              <li className="property-card" key={property.id}>
                <div className="property-card-main">
                  <span className="property-mark" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none">
                      <path d="M4 20V7.5L12 4l8 3.5V20M2.5 20h19M9 20v-5h6v5M8 9h.01M16 9h.01" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </span>
                  <div className="property-details">
                    <h4>{property.name}</h4>
                    <p>{property.address}</p>
                  </div>
                </div>
                <div className={`unit-count${property.unitError ? ' unit-count-error' : ''}`}>
                  {property.unitError ? (
                    <>
                      <span>Unit count unavailable</span>
                      <small>{property.unitError}</small>
                    </>
                  ) : (
                    <>
                      <strong>{property.unitCount}</strong>
                      <span>{property.unitCount === 1 ? 'unit' : 'units'}</span>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

function PropertyForm({ onCancel, onCreated }) {
  const [name, setName] = useState('')
  const [address, setAddress] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    const cleanName = name.trim()
    const cleanAddress = address.trim()
    if (!cleanName || !cleanAddress) {
      setError('Enter both a property name and address.')
      return
    }
    if (cleanName.length > 150 || cleanAddress.length > 255) {
      setError('Property names must be 150 characters or fewer and addresses 255 characters or fewer.')
      return
    }

    setIsSaving(true)
    try {
      await apiRequest('/api/properties', {
        method: 'POST',
        authenticated: true,
        body: { name: cleanName, address: cleanAddress },
      })
      onCreated()
    } catch (requestError) {
      setError(requestError.message || 'Unable to add this property. Please try again.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <form className="management-form" onSubmit={handleSubmit} noValidate aria-labelledby="property-form-title">
      <div className="management-form-heading">
        <h3 id="property-form-title">Add property</h3>
        <button className="text-button" type="button" onClick={onCancel} disabled={isSaving}>Cancel</button>
      </div>
      {error && <div className="form-error" role="alert">{error}</div>}
      <div className="management-fields">
        <div className="field-group">
          <label htmlFor="property-name">Property name</label>
          <input id="property-name" name="name" value={name} maxLength={150} autoComplete="off" disabled={isSaving} required onChange={(event) => setName(event.target.value)} />
        </div>
        <div className="field-group">
          <label htmlFor="property-address">Address</label>
          <input id="property-address" name="address" value={address} maxLength={255} autoComplete="street-address" disabled={isSaving} required onChange={(event) => setAddress(event.target.value)} />
        </div>
      </div>
      <div className="management-form-actions">
        <button className="primary-button compact-button" type="submit" disabled={isSaving}>
          {isSaving ? 'Saving…' : 'Save property'}
        </button>
      </div>
    </form>
  )
}

function UnitForm({ propertyId, onCancel, onCreated }) {
  const [unitNumber, setUnitNumber] = useState('')
  const [bedrooms, setBedrooms] = useState('1')
  const [monthlyRent, setMonthlyRent] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    const cleanNumber = unitNumber.trim()
    const bedroomCount = Number(bedrooms)
    if (!cleanNumber || cleanNumber.length > 50) {
      setError('Enter a unit number of 50 characters or fewer.')
      return
    }
    if (!bedrooms.trim() || !Number.isInteger(bedroomCount) || bedroomCount < 0) {
      setError('Bedrooms must be a whole number of zero or more.')
      return
    }
    if (!/^\d+(?:\.\d{1,2})?$/.test(monthlyRent.trim())) {
      setError('Enter a non-negative rent amount with no more than two decimal places.')
      return
    }
    const wholeRent = monthlyRent.trim().split('.')[0].replace(/^0+/, '') || '0'
    if (wholeRent.length > 10) {
      setError('Monthly rent is too large.')
      return
    }

    setIsSaving(true)
    try {
      await apiRequest(`/api/properties/${encodeURIComponent(propertyId)}/units`, {
        method: 'POST',
        authenticated: true,
        body: { unit_number: cleanNumber, bedrooms: bedroomCount, monthly_rent: monthlyRent.trim() },
      })
      onCreated()
    } catch (requestError) {
      setError(requestError.message || 'Unable to add this unit. Please try again.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <form className="management-form" onSubmit={handleSubmit} noValidate aria-labelledby="unit-form-title">
      <div className="management-form-heading">
        <h3 id="unit-form-title">Add unit</h3>
        <button className="text-button" type="button" onClick={onCancel} disabled={isSaving}>Cancel</button>
      </div>
      {error && <div className="form-error" role="alert">{error}</div>}
      <div className="management-fields unit-fields">
        <div className="field-group">
          <label htmlFor="unit-number">Unit number</label>
          <input id="unit-number" name="unit_number" value={unitNumber} maxLength={50} autoComplete="off" disabled={isSaving} required onChange={(event) => setUnitNumber(event.target.value)} />
        </div>
        <div className="field-group">
          <label htmlFor="unit-bedrooms">Bedrooms</label>
          <input id="unit-bedrooms" name="bedrooms" type="number" min="0" step="1" value={bedrooms} disabled={isSaving} required onChange={(event) => setBedrooms(event.target.value)} />
        </div>
        <div className="field-group">
          <label htmlFor="unit-rent">Monthly rent (KES)</label>
          <input id="unit-rent" name="monthly_rent" type="text" inputMode="decimal" placeholder="e.g. 15000.00" value={monthlyRent} disabled={isSaving} required onChange={(event) => setMonthlyRent(event.target.value)} />
        </div>
      </div>
      <div className="management-form-actions">
        <button className="primary-button compact-button" type="submit" disabled={isSaving}>
          {isSaving ? 'Saving…' : 'Save unit'}
        </button>
      </div>
    </form>
  )
}

function formatKes(amount) {
  const [wholePart = '0', fractionalPart = ''] = String(amount).split('.')
  const groupedWhole = wholePart.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `KES ${groupedWhole}.${fractionalPart.padEnd(2, '0').slice(0, 2)}`
}

function PropertiesPage({ onDataChanged }) {
  const [properties, setProperties] = useState([])
  const [selectedProperty, setSelectedProperty] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [listError, setListError] = useState('')
  const [showPropertyForm, setShowPropertyForm] = useState(false)
  const [showUnitForm, setShowUnitForm] = useState(false)
  const [propertyReload, setPropertyReload] = useState(0)
  const [unitReload, setUnitReload] = useState(0)
  const [unitsState, setUnitsState] = useState({ loading: true, units: [], error: '' })
  const selectedPropertyId = selectedProperty?.id

  useEffect(() => {
    let isCurrent = true
    async function fetchProperties() {
      setIsLoading(true)
      setListError('')
      try {
        const result = await apiRequest('/api/properties', { authenticated: true })
        if (!Array.isArray(result?.properties)) throw new Error('The property list could not be read.')
        if (isCurrent) setProperties(result.properties)
      } catch (error) {
        if (isCurrent) setListError(error.message || 'Unable to load properties. Please try again.')
      } finally {
        if (isCurrent) setIsLoading(false)
      }
    }
    fetchProperties()
    return () => { isCurrent = false }
  }, [propertyReload])

  useEffect(() => {
    if (!selectedPropertyId) return undefined
    let isCurrent = true
    async function fetchUnits() {
      setUnitsState({ loading: true, units: [], error: '' })
      try {
        const result = await apiRequest(
          `/api/properties/${encodeURIComponent(selectedPropertyId)}/units`,
          { authenticated: true },
        )
        if (!Array.isArray(result?.units)) throw new Error('The unit list could not be read.')
        if (isCurrent) setUnitsState({ loading: false, units: result.units, error: '' })
      } catch (error) {
        if (isCurrent) setUnitsState({ loading: false, units: [], error: error.message || 'Unable to load units.' })
      }
    }
    fetchUnits()
    return () => { isCurrent = false }
  }, [selectedPropertyId, unitReload])

  function propertyCreated() {
    setShowPropertyForm(false)
    setPropertyReload((count) => count + 1)
    onDataChanged()
  }

  function unitCreated() {
    setShowUnitForm(false)
    setUnitReload((count) => count + 1)
    onDataChanged()
  }

  if (selectedProperty) {
    return (
      <section className="management-page" aria-labelledby="property-detail-heading">
        <button className="back-button" type="button" onClick={() => { setSelectedProperty(null); setShowUnitForm(false) }}>
          <span aria-hidden="true">←</span> All properties
        </button>
        <div className="management-page-heading detail-heading">
          <div>
            <p className="eyebrow">Property</p>
            <h2 id="property-detail-heading">{selectedProperty.name}</h2>
            <p>{selectedProperty.address}</p>
          </div>
          <button className="primary-button compact-button" type="button" onClick={() => setShowUnitForm(true)}>Add unit</button>
        </div>
        {showUnitForm && <UnitForm propertyId={selectedProperty.id} onCancel={() => setShowUnitForm(false)} onCreated={unitCreated} />}
        <section className="unit-section" aria-labelledby="unit-list-heading">
          <div className="property-section-heading">
            <h3 id="unit-list-heading">Units</h3>
            {!unitsState.loading && !unitsState.error && (
              <span className="property-total">{unitsState.units.length} {unitsState.units.length === 1 ? 'unit' : 'units'}</span>
            )}
          </div>
          {unitsState.loading ? (
            <div className="overview-message" role="status" aria-live="polite"><span className="loading-dot" aria-hidden="true" /> Loading units…</div>
          ) : unitsState.error ? (
            <div className="overview-message overview-error" role="alert">
              <div><h4>Units could not be loaded</h4><p>{unitsState.error}</p></div>
              <button className="retry-button" type="button" onClick={() => setUnitReload((count) => count + 1)}>Try again</button>
            </div>
          ) : unitsState.units.length === 0 ? (
            <div className="overview-empty compact-empty">
              <h4>No units yet</h4>
              <p>Add the units in this property to keep their rent and occupancy records together.</p>
            </div>
          ) : (
            <ul className="unit-list">
              {unitsState.units.map((unit) => (
                <li className="unit-card" key={unit.id}>
                  <div className="unit-card-main">
                    <h4>{unit.unit_number}</h4>
                    <p>{unit.bedrooms} {unit.bedrooms === 1 ? 'bedroom' : 'bedrooms'}</p>
                  </div>
                  <div className="unit-card-meta">
                    <strong>{formatKes(unit.monthly_rent)}</strong>
                    <span className={`status-pill${unit.is_active ? ' is-active' : ''}`}>{unit.is_active ? 'Active' : 'Inactive'}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </section>
    )
  }

  return (
    <section className="management-page" aria-labelledby="properties-page-heading">
      <div className="management-page-heading">
        <div>
          <p className="eyebrow">Your portfolio</p>
          <h2 id="properties-page-heading">Properties</h2>
          <p>Manage your properties and the units within each one.</p>
        </div>
        <button className="primary-button compact-button" type="button" onClick={() => setShowPropertyForm(true)}>Add property</button>
      </div>
      {showPropertyForm && <PropertyForm onCancel={() => setShowPropertyForm(false)} onCreated={propertyCreated} />}
      {isLoading ? (
        <div className="overview-message" role="status" aria-live="polite"><span className="loading-dot" aria-hidden="true" /> Loading properties…</div>
      ) : listError ? (
        <div className="overview-message overview-error" role="alert">
          <div><h4>Properties could not be loaded</h4><p>{listError}</p></div>
          <button className="retry-button" type="button" onClick={() => setPropertyReload((count) => count + 1)}>Try again</button>
        </div>
      ) : properties.length === 0 ? (
        <div className="overview-empty compact-empty">
          <div className="empty-icon" aria-hidden="true">
            <svg viewBox="0 0 40 40" fill="none">
              <path d="M7 18.5 20 8l13 10.5V32H7V18.5Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
              <path d="M16 32V22h8v10M12 19h.01M28 19h.01" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
          </div>
          <h4>No properties yet</h4>
          <p>Add a property to start keeping its address and units in one place.</p>
        </div>
      ) : (
        <ul className="management-property-list">
          {properties.map((property) => (
            <li key={property.id}>
              <button className="management-property-card" type="button" onClick={() => setSelectedProperty(property)}>
                <span className="property-mark" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none">
                    <path d="M4 20V7.5L12 4l8 3.5V20M2.5 20h19M9 20v-5h6v5M8 9h.01M16 9h.01" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </span>
                <span className="management-property-details"><strong>{property.name}</strong><span>{property.address}</span></span>
                <span className="property-open-label">View units <span aria-hidden="true">→</span></span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function DashboardShell({ user }) {
  const { logout } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  const [page, setPage] = useState('Overview')
  const [dataVersion, setDataVersion] = useState(0)
  const menuButtonRef = useRef(null)
  const activeNavRef = useRef(null)

  useEffect(() => {
    if (!menuOpen) return undefined

    activeNavRef.current?.focus()
    function handleKeyDown(event) {
      if (event.key === 'Escape') {
        setMenuOpen(false)
        menuButtonRef.current?.focus()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [menuOpen])

  function navigateTo(label) {
    setPage(label)
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
        <a className="brand sidebar-brand" href="#overview" onClick={() => navigateTo('Overview')}>
          <span className="brand-mark" aria-hidden="true">N</span>
          <span>NyumbaFlow</span>
        </a>
        <p className="sidebar-label">Workspace</p>
        <nav id="workspace-navigation" aria-label="Workspace">
          {navigationItems.map((item) => item.available ? (
            <button
              className={`nav-item${page === item.label ? ' is-active' : ''}`}
              type="button"
              key={item.label}
              aria-current={page === item.label ? 'page' : undefined}
              ref={page === item.label ? activeNavRef : undefined}
              onClick={() => navigateTo(item.label)}
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
            <h1>{page}</h1>
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
          {page === 'Overview' ? (
            <>
              <section className="overview-intro" aria-labelledby="welcome-heading">
                <p className="eyebrow">Your workspace</p>
                <h2 id="welcome-heading">Welcome{user.full_name ? `, ${user.full_name.split(' ')[0]}` : ''}.</h2>
                <p>Manage your properties and keep the important details of your rental business in view.</p>
              </section>
              <PropertyOverview refreshKey={dataVersion} />
            </>
          ) : (
            <PropertiesPage onDataChanged={() => setDataVersion((version) => version + 1)} />
          )}
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
