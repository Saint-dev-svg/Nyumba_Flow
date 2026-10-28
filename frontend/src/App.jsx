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
  { label: 'Financial Overview', available: true },
  { label: 'Properties', available: true },
  { label: 'Tenants', available: true },
  { label: 'Leases', available: true },
  { label: 'Monthly Billing', available: true },
  { label: 'Rent Invoices', available: true },
  { label: 'Utilities Invoices', available: true },
  { label: 'Other Invoices', available: true },
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

function TenantForm({ tenant, onCancel, onSaved }) {
  const [fullName, setFullName] = useState(tenant?.full_name || '')
  const [email, setEmail] = useState(tenant?.email || '')
  const [phoneNumber, setPhoneNumber] = useState(tenant?.phone_number || '')
  const [nationalIdLast4, setNationalIdLast4] = useState(tenant?.national_id_last4 || '')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')
  const isEditing = Boolean(tenant)

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    const cleanName = fullName.trim()
    const cleanEmail = email.trim().toLowerCase()
    const cleanPhone = phoneNumber.trim()
    const cleanLast4 = nationalIdLast4.trim()

    if (!cleanName || cleanName.length > 120) {
      setError('Full name is required and must be at most 120 characters.')
      return
    }
    if (!cleanEmail || cleanEmail.length > 255 || !cleanEmail.includes('@') || /\s/.test(cleanEmail)) {
      setError('Enter a valid email address of at most 255 characters.')
      return
    }
    if (cleanPhone.length > 30) {
      setError('Phone number must be at most 30 characters.')
      return
    }
    if (cleanLast4 && !/^\d{4}$/.test(cleanLast4)) {
      setError('National ID last four must contain exactly 4 digits.')
      return
    }

    setIsSaving(true)
    try {
      const body = {
        full_name: cleanName,
        email: cleanEmail,
        phone_number: cleanPhone || null,
        national_id_last4: cleanLast4 || null,
      }
      await apiRequest(isEditing ? `/api/tenants/${encodeURIComponent(tenant.id)}` : '/api/tenants', {
        method: isEditing ? 'PATCH' : 'POST',
        authenticated: true,
        body,
      })
      onSaved()
    } catch (requestError) {
      setError(requestError.message || `Unable to ${isEditing ? 'update' : 'register'} tenant. Please try again.`)
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <form className="management-form" onSubmit={handleSubmit} noValidate aria-labelledby="tenant-form-title">
      <div className="management-form-heading">
        <h3 id="tenant-form-title">{isEditing ? 'Edit tenant details' : 'Register tenant'}</h3>
        <button className="text-button" type="button" onClick={onCancel} disabled={isSaving}>Cancel</button>
      </div>
      {error && <div className="form-error" role="alert">{error}</div>}
      <div className="management-fields tenant-fields">
        <div className="field-group">
          <label htmlFor="tenant-full-name">Full name</label>
          <input id="tenant-full-name" name="full_name" value={fullName} maxLength={120} autoComplete="name" disabled={isSaving} required onChange={(event) => setFullName(event.target.value)} />
        </div>
        <div className="field-group">
          <label htmlFor="tenant-email">Email address</label>
          <input id="tenant-email" name="email" type="email" inputMode="email" value={email} maxLength={255} autoComplete="email" disabled={isSaving} required onChange={(event) => setEmail(event.target.value)} />
        </div>
        <div className="field-group">
          <label htmlFor="tenant-phone">Phone number <span className="optional-label">Optional</span></label>
          <input id="tenant-phone" name="phone_number" type="tel" value={phoneNumber} maxLength={30} autoComplete="tel" disabled={isSaving} onChange={(event) => setPhoneNumber(event.target.value)} />
        </div>
        <div className="field-group">
          <label htmlFor="tenant-national-id">National ID last four <span className="optional-label">Optional</span></label>
          <input id="tenant-national-id" name="national_id_last4" type="text" inputMode="numeric" value={nationalIdLast4} maxLength={4} autoComplete="off" disabled={isSaving} onChange={(event) => setNationalIdLast4(event.target.value)} />
        </div>
      </div>
      <div className="management-form-actions">
        <button className="primary-button compact-button" type="submit" disabled={isSaving}>
          {isSaving ? 'Saving…' : isEditing ? 'Save changes' : 'Register tenant'}
        </button>
      </div>
    </form>
  )
}

function TenantsPage() {
  const [tenants, setTenants] = useState([])
  const [selectedTenantId, setSelectedTenantId] = useState(null)
  const [tenantDetails, setTenantDetails] = useState({ loading: false, tenant: null, error: '' })
  const [isLoading, setIsLoading] = useState(true)
  const [listError, setListError] = useState('')
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [listReload, setListReload] = useState(0)
  const [detailReload, setDetailReload] = useState(0)
  const [showStatement, setShowStatement] = useState(false)

  useEffect(() => {
    let isCurrent = true
    async function fetchTenants() {
      setIsLoading(true)
      setListError('')
      try {
        const result = await apiRequest('/api/tenants', { authenticated: true })
        if (!Array.isArray(result?.tenants)) throw new Error('The tenant list could not be read. Please try again.')
        if (isCurrent) setTenants(result.tenants)
      } catch (error) {
        if (isCurrent) setListError(error.message || 'Unable to load tenants. Please try again.')
      } finally {
        if (isCurrent) setIsLoading(false)
      }
    }
    fetchTenants()
    return () => { isCurrent = false }
  }, [listReload])

  useEffect(() => {
    if (selectedTenantId === null) return undefined
    let isCurrent = true
    async function fetchTenant() {
      setTenantDetails({ loading: true, tenant: null, error: '' })
      try {
        const result = await apiRequest(`/api/tenants/${encodeURIComponent(selectedTenantId)}`, { authenticated: true })
        if (!result?.tenant) throw new Error('Tenant details could not be read. Please try again.')
        if (isCurrent) setTenantDetails({ loading: false, tenant: result.tenant, error: '' })
      } catch (error) {
        if (isCurrent) setTenantDetails({ loading: false, tenant: null, error: error.message || 'Unable to load tenant details.' })
      }
    }
    fetchTenant()
    return () => { isCurrent = false }
  }, [selectedTenantId, detailReload])

  function tenantSaved() {
    setShowCreateForm(false)
    setIsEditing(false)
    setListReload((count) => count + 1)
    if (selectedTenantId !== null) setDetailReload((count) => count + 1)
  }

  function closeTenantDetails() {
    setSelectedTenantId(null)
    setTenantDetails({ loading: false, tenant: null, error: '' })
    setIsEditing(false)
    setShowStatement(false)
  }

  if (selectedTenantId !== null) {
    return (
      <section className="management-page" aria-labelledby="tenant-detail-heading">
        <button className="back-button" type="button" onClick={closeTenantDetails}>
          <span aria-hidden="true">←</span> All tenants
        </button>
        {tenantDetails.loading ? (
          <div className="overview-message" role="status" aria-live="polite"><span className="loading-dot" aria-hidden="true" /> Loading tenant details…</div>
        ) : tenantDetails.error ? (
          <div className="overview-message overview-error" role="alert">
            <div><h4>Tenant details could not be loaded</h4><p>{tenantDetails.error}</p></div>
            <button className="retry-button" type="button" onClick={() => setDetailReload((count) => count + 1)}>Try again</button>
          </div>
        ) : tenantDetails.tenant && (
          <>
            <div className="management-page-heading detail-heading">
              <div>
                <p className="eyebrow">Tenant record</p>
                <h2 id="tenant-detail-heading">{tenantDetails.tenant.full_name}</h2>
                <p>{tenantDetails.tenant.email}</p>
              </div>
              {!isEditing && (
                <div className="tenant-detail-actions">
                  <button className="secondary-button compact-button" type="button" onClick={() => setShowStatement(true)}>View statement</button>
                  <button className="primary-button compact-button" type="button" onClick={() => setIsEditing(true)}>Edit details</button>
                </div>
              )}
            </div>
            {isEditing ? (
              <TenantForm tenant={tenantDetails.tenant} onCancel={() => setIsEditing(false)} onSaved={tenantSaved} />
            ) : (
              <dl className="tenant-detail-card">
                <div><dt>Full name</dt><dd>{tenantDetails.tenant.full_name}</dd></div>
                <div><dt>Email address</dt><dd>{tenantDetails.tenant.email}</dd></div>
                <div><dt>Phone number</dt><dd>{tenantDetails.tenant.phone_number || 'Not provided'}</dd></div>
                <div><dt>National ID last four</dt><dd>{tenantDetails.tenant.national_id_last4 || 'Not provided'}</dd></div>
              </dl>
            )}
          </>
        )}
        {showStatement && !isEditing && tenantDetails.tenant && (
          <TenantStatement tenant={tenantDetails.tenant} onBack={() => setShowStatement(false)} />
        )}
      </section>
    )
  }

  return (
    <section className="management-page" aria-labelledby="tenants-page-heading">
      <div className="management-page-heading">
        <div>
          <p className="eyebrow">People</p>
          <h2 id="tenants-page-heading">Tenants</h2>
          <p>Keep tenant contact details available for your property records.</p>
        </div>
        <button className="primary-button compact-button" type="button" onClick={() => setShowCreateForm(true)}>Register tenant</button>
      </div>
      {showCreateForm && <TenantForm onCancel={() => setShowCreateForm(false)} onSaved={tenantSaved} />}
      {isLoading ? (
        <div className="overview-message" role="status" aria-live="polite"><span className="loading-dot" aria-hidden="true" /> Loading tenants…</div>
      ) : listError ? (
        <div className="overview-message overview-error" role="alert">
          <div><h4>Tenants could not be loaded</h4><p>{listError}</p></div>
          <button className="retry-button" type="button" onClick={() => setListReload((count) => count + 1)}>Try again</button>
        </div>
      ) : tenants.length === 0 ? (
        <div className="overview-empty compact-empty">
          <div className="empty-icon" aria-hidden="true">
            <svg viewBox="0 0 40 40" fill="none">
              <circle cx="20" cy="13" r="6" stroke="currentColor" strokeWidth="1.7" />
              <path d="M8 33c.8-6.1 5.4-9.5 12-9.5s11.2 3.4 12 9.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
          </div>
          <h4>No tenants yet</h4>
          <p>Register a tenant to keep their contact details with your property records.</p>
        </div>
      ) : (
        <ul className="tenant-list">
          {tenants.map((tenant) => (
            <li key={tenant.id}>
              <button className="tenant-list-card" type="button" onClick={() => setSelectedTenantId(tenant.id)}>
                <span className="tenant-avatar" aria-hidden="true">{tenant.full_name.trim().charAt(0).toUpperCase()}</span>
                <span className="tenant-list-details">
                  <strong>{tenant.full_name}</strong>
                  <span>{tenant.email}</span>
                </span>
                <span className="tenant-list-phone">{tenant.phone_number || 'No phone number'}</span>
                <span className="property-open-label">View details <span aria-hidden="true">→</span></span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function formatStatementMoney(value, currency = 'KES') {
  if (value === null || value === undefined) return '—'
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(String(value))
  if (!match) return '—'
  const [, sign, whole, fraction = ''] = match
  const groupedWhole = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  const amount = `${sign}${groupedWhole}.${fraction.padEnd(2, '0').slice(0, 2)}`
  return currency === 'KES' ? `KSh ${amount}` : `${currency} ${amount}`
}

function formatStatementDate(value, includeTime = false) {
  if (!value) return '—'
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value)
  const parsed = new Date(dateOnly ? `${value}T00:00:00Z` : value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat('en-KE', {
    dateStyle: 'medium',
    ...(includeTime ? { timeStyle: 'short' } : {}),
    timeZone: dateOnly ? 'UTC' : 'Africa/Nairobi',
  }).format(parsed)
}

function statementPurposeLabel(purpose) {
  return ({ rent: 'Rent', utilities: 'Utilities', other: 'Other' })[purpose] || 'Other'
}

function isValidStatementDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

function TenantStatement({ tenant, onBack }) {
  const [filters, setFilters] = useState({ startDate: '', endDate: '' })
  const [appliedRange, setAppliedRange] = useState({ startDate: '', endDate: '' })
  const [rangeError, setRangeError] = useState('')
  const [statementState, setStatementState] = useState({ loading: true, statement: null, error: '' })
  const [retryCount, setRetryCount] = useState(0)

  useEffect(() => {
    const printScopeClass = 'tenant-statement-print-active'
    document.body.classList.add(printScopeClass)
    return () => document.body.classList.remove(printScopeClass)
  }, [])

  useEffect(() => {
    let isCurrent = true

    async function fetchStatement() {
      setStatementState({ loading: true, statement: null, error: '' })
      const params = new URLSearchParams()
      if (appliedRange.startDate) params.set('start_date', appliedRange.startDate)
      if (appliedRange.endDate) params.set('end_date', appliedRange.endDate)
      const query = params.toString()
      const path = `/api/tenants/${encodeURIComponent(tenant.id)}/statement${query ? `?${query}` : ''}`

      try {
        const result = await apiRequest(path, { authenticated: true })
        if (
          !result?.tenant
          || !Array.isArray(result.invoices)
          || !Array.isArray(result.payments)
          || !Array.isArray(result.transaction_history)
          || !result.summary
        ) {
          throw new Error('The tenant statement could not be read. Please try again.')
        }
        if (isCurrent) setStatementState({ loading: false, statement: result, error: '' })
      } catch (error) {
        if (isCurrent) {
          setStatementState({ loading: false, statement: null, error: error.message || 'Unable to load this statement. Please try again.' })
        }
      }
    }

    fetchStatement()
    return () => { isCurrent = false }
  }, [tenant.id, appliedRange, retryCount])

  function applyFilters(event) {
    event.preventDefault()
    const { startDate, endDate } = filters
    if (startDate && !isValidStatementDate(startDate)) {
      setRangeError('Enter a valid start date.')
      return
    }
    if (endDate && !isValidStatementDate(endDate)) {
      setRangeError('Enter a valid end date.')
      return
    }
    if (startDate && endDate && startDate > endDate) {
      setRangeError('Start date must be on or before the end date.')
      return
    }
    setRangeError('')
    setAppliedRange({ startDate, endDate })
    setRetryCount((count) => count + 1)
  }

  function resetFilters() {
    setFilters({ startDate: '', endDate: '' })
    setAppliedRange({ startDate: '', endDate: '' })
    setRangeError('')
    setRetryCount((count) => count + 1)
  }

  const statement = statementState.statement
  const periodLabel = !appliedRange.startDate && !appliedRange.endDate
    ? 'All available history'
    : appliedRange.startDate && appliedRange.endDate
      ? `${formatStatementDate(appliedRange.startDate)} – ${formatStatementDate(appliedRange.endDate)} (inclusive)`
      : appliedRange.startDate
        ? `From ${formatStatementDate(appliedRange.startDate)} onward`
        : `Through ${formatStatementDate(appliedRange.endDate)} (inclusive)`
  const hasActivity = Boolean(statement && (
    statement.invoices.length || statement.payments.length || statement.transaction_history.length
  ))

  return (
    <div className="tenant-statement-print-root">
      <div className="tenant-statement-toolbar statement-screen-only">
        <button className="back-button" type="button" onClick={onBack}><span aria-hidden="true">←</span> Tenant details</button>
        <button className="secondary-button compact-button" type="button" onClick={() => window.print()} disabled={!statement || statementState.loading}>Print statement</button>
      </div>
      <div className="management-page-heading tenant-statement-heading">
        <div>
          <p className="eyebrow">Tenant account</p>
          <h2>Statement for {tenant.full_name}</h2>
          <p>{tenant.email}</p>
        </div>
      </div>

      <form className="tenant-statement-filters statement-screen-only" onSubmit={applyFilters}>
        <div className="field-group">
          <label htmlFor="statement-start-date">Start date</label>
          <input id="statement-start-date" type="date" value={filters.startDate} onChange={(event) => setFilters((current) => ({ ...current, startDate: event.target.value }))} />
        </div>
        <div className="field-group">
          <label htmlFor="statement-end-date">End date</label>
          <input id="statement-end-date" type="date" value={filters.endDate} onChange={(event) => setFilters((current) => ({ ...current, endDate: event.target.value }))} />
        </div>
        <div className="tenant-statement-filter-actions">
          <button className="primary-button compact-button" type="submit" disabled={statementState.loading}>Apply filters</button>
          <button className="secondary-button compact-button" type="button" onClick={resetFilters} disabled={statementState.loading && !appliedRange.startDate && !appliedRange.endDate}>All history</button>
        </div>
        {rangeError && <p className="form-error tenant-statement-range-error" role="alert">{rangeError}</p>}
      </form>

      <p className="tenant-statement-period"><strong>Activity period:</strong> {periodLabel} <span>· Dates use Africa/Nairobi local time.</span></p>
      {statementState.loading ? (
        <div className="overview-message" role="status" aria-live="polite"><span className="loading-dot" aria-hidden="true" /> Loading tenant statement…</div>
      ) : statementState.error ? (
        <div className="overview-message overview-error statement-screen-only" role="alert">
          <div><h4>Statement could not be loaded</h4><p>{statementState.error}</p></div>
          <button className="retry-button" type="button" onClick={() => setRetryCount((count) => count + 1)}>Try again</button>
        </div>
      ) : statement ? (
        <>
          <p className="tenant-statement-explanation">Receipt totals use the payment received date. Allocation credits use the date funds were applied to charges. Current outstanding balances reflect issued invoices as of now, independent of this activity period.</p>
          <section className="tenant-statement-summary" aria-label="Statement financial summary">
            <StatementSummaryCard title="Billed during period" totals={statement.summary.billed_during_period} />
            <StatementSummaryCard title="Allocated during period" totals={statement.summary.allocated_during_period} />
            <article className="tenant-statement-summary-card">
              <h3>Payments received during period</h3>
              <strong>{formatStatementMoney(statement.summary.payments_received_during_period)}</strong>
              <p>Gross receipts, counted by received date.</p>
            </article>
            <StatementSummaryCard title="Current outstanding balance" totals={statement.summary.current_outstanding_balance} note="Current balance on issued invoices." />
          </section>

          {!hasActivity ? (
            <div className="overview-empty compact-empty tenant-statement-empty">
              <h3>No financial activity for this tenant</h3>
              <p>No issued invoices, received payments, or allocations were found for the selected period.</p>
            </div>
          ) : (
            <>
              <section className="tenant-statement-section" aria-labelledby="statement-invoices-heading">
                <div className="property-section-heading"><div><p className="eyebrow">Billing activity</p><h3 id="statement-invoices-heading">Invoices issued in period</h3></div></div>
                {statement.invoices.length === 0 ? <p className="tenant-statement-no-items">No invoices were issued during this period.</p> : (
                  <ul className="tenant-statement-invoice-list">
                    {statement.invoices.map((invoice) => (
                      <li className="tenant-statement-invoice" key={invoice.id}>
                        <div className="tenant-statement-item-heading">
                          <div><h4>Invoice #{invoice.id} · {statementPurposeLabel(invoice.purpose)}</h4><p>{invoice.property?.name || 'Property unavailable'} · Unit {invoice.unit?.unit_number || '—'}</p></div>
                          <span className={`invoice-lifecycle status-${invoice.status}`}>{invoice.status || 'Unknown'}</span>
                        </div>
                        <p className="tenant-statement-item-subtitle">Billing period {formatStatementDate(invoice.period_start)} – {formatStatementDate(invoice.period_end)} · Issued {formatStatementDate(invoice.issued_at, true)} · Due {formatStatementDate(invoice.due_date)}</p>
                        <div className="tenant-statement-invoice-totals">
                          <span>Total <strong>{formatStatementMoney(invoice.total_amount)}</strong></span>
                          <span>Paid to date <strong>{formatStatementMoney(invoice.current_paid_amount)}</strong></span>
                          <span>Outstanding now <strong>{formatStatementMoney(invoice.current_outstanding_balance)}</strong></span>
                          <span>Allocated in period <strong>{formatStatementMoney(invoice.allocations_during_period)}</strong></span>
                        </div>
                        {invoice.charges?.length > 0 && <ul className="tenant-statement-charges">
                          {invoice.charges.map((charge) => <li key={charge.id}>
                            <div><strong>{charge.description || `${statementPurposeLabel(charge.category)} charge`}</strong><span>{statementPurposeLabel(charge.category)}</span></div>
                            <strong>{formatStatementMoney(charge.amount)}</strong>
                            {charge.utility_breakdowns?.length > 0 && <ul className="tenant-statement-breakdowns">
                              {charge.utility_breakdowns.map((breakdown) => <li key={breakdown.category}>{breakdown.category === 'water' ? 'Water' : breakdown.category === 'garbage' ? 'Garbage' : breakdown.category}: {formatStatementMoney(breakdown.amount)}</li>)}
                            </ul>}
                          </li>)}
                        </ul>}
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className="tenant-statement-section" aria-labelledby="statement-payments-heading">
                <div className="property-section-heading"><div><p className="eyebrow">Receipts and allocations</p><h3 id="statement-payments-heading">Payment history</h3></div></div>
                {statement.payments.length === 0 ? <p className="tenant-statement-no-items">No payments were received or allocated during this period.</p> : (
                  <ul className="tenant-statement-payment-list">
                    {statement.payments.map((payment) => <li className="tenant-statement-payment" key={payment.id}>
                      <div className="tenant-statement-item-heading">
                        <div><h4>{payment.receipt_number || `Payment #${payment.id}`}</h4><p>Received {formatStatementDate(payment.received_at, true)} · {payment.method || 'Payment method unavailable'}</p></div>
                        <strong>{formatStatementMoney(payment.amount, payment.currency)}</strong>
                      </div>
                      <div className="tenant-statement-payment-meta">
                        <span>Allocated in period <strong>{formatStatementMoney(payment.allocated_amount_during_period)}</strong></span>
                        <span>Currently allocated <strong>{formatStatementMoney(payment.current_allocated_amount)}</strong></span>
                        <span>Currently unallocated <strong>{formatStatementMoney(payment.current_unallocated_amount)}</strong></span>
                      </div>
                      {payment.allocations?.length > 0 && <ul className="tenant-statement-allocation-list">
                        {payment.allocations.map((allocation, index) => <li key={`${allocation.invoice_id}-${allocation.charge_id}-${index}`}>
                          <span>Invoice #{allocation.invoice_id} · {statementPurposeLabel(allocation.purpose)} · {allocation.description || statementPurposeLabel(allocation.charge_category)}</span>
                          <span>Allocated {formatStatementDate(allocation.allocated_at, true)}</span>
                          <strong>{formatStatementMoney(allocation.amount)}</strong>
                        </li>)}
                      </ul>}
                    </li>)}
                  </ul>
                )}
              </section>

              <section className="tenant-statement-section" aria-labelledby="statement-activity-heading">
                <div className="property-section-heading"><div><p className="eyebrow">Dated entries</p><h3 id="statement-activity-heading">Transaction history</h3></div></div>
                {statement.transaction_history.length === 0 ? <p className="tenant-statement-no-items">No invoice or allocation entries fall within this period.</p> : (
                  <ul className="tenant-statement-transaction-list">
                    {statement.transaction_history.map((event, index) => <li className="tenant-statement-transaction" key={`${event.type}-${event.invoice_id}-${event.charge_id}-${event.event_at}-${index}`}>
                      <div><strong>{event.type === 'invoice_charge' ? 'Invoice charge' : 'Payment allocation'}</strong><span>{formatStatementDate(event.event_at, true)}</span></div>
                      <div><span>Invoice #{event.invoice_id} · {statementPurposeLabel(event.purpose)}</span><span>{event.description || '—'}</span></div>
                      <strong>{formatStatementMoney(event.amount)}</strong>
                    </li>)}
                  </ul>
                )}
              </section>
            </>
          )}
        </>
      ) : null}
    </div>
  )
}

function StatementSummaryCard({ title, totals, note }) {
  return (
    <article className="tenant-statement-summary-card">
      <h3>{title}</h3>
      <strong>{formatStatementMoney(totals?.total)}</strong>
      <dl>
        {['rent', 'utilities', 'other'].map((category) => <div key={category}>
          <dt>{statementPurposeLabel(category)}</dt><dd>{formatStatementMoney(totals?.[category])}</dd>
        </div>)}
      </dl>
      {note && <p>{note}</p>}
    </article>
  )
}

function LeaseForm({ tenants, properties, units, leases, onCancel, onCreated }) {
  const [tenantId, setTenantId] = useState('')
  const [unitId, setUnitId] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [monthlyRent, setMonthlyRent] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')

  const activeUnits = units.filter((unit) => unit.is_active)
  const selectedUnit = activeUnits.find((unit) => String(unit.id) === unitId)
  const selectedTenant = tenants.find((tenant) => String(tenant.id) === tenantId)
  const hasOverlap = Boolean(selectedUnit && startDate && leases.some((lease) => (
    lease.is_active && lease.unit_id === selectedUnit.id && leaseOverlaps(lease, startDate, endDate || null)
  )))

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    if (!tenantId || !selectedTenant) {
      setError('Select a tenant for this lease.')
      return
    }
    if (!unitId || !selectedUnit) {
      setError('Select an active unit for this lease.')
      return
    }
    if (!startDate) {
      setError('A start date is required.')
      return
    }
    if (endDate && endDate < startDate) {
      setError('End date cannot be before start date.')
      return
    }
    if (!/^\d+(?:\.\d{1,2})?$/.test(monthlyRent.trim())) {
      setError('Enter a non-negative monthly rent with no more than two decimal places.')
      return
    }
    const wholeRent = monthlyRent.trim().split('.')[0].replace(/^0+/, '') || '0'
    if (wholeRent.length > 10) {
      setError('Agreed monthly rent is too large.')
      return
    }

    const body = {
      tenant_id: Number(tenantId),
      unit_id: Number(unitId),
      start_date: startDate,
      monthly_rent: monthlyRent.trim(),
    }
    if (endDate) body.end_date = endDate

    setIsSaving(true)
    try {
      await apiRequest('/api/leases', { method: 'POST', authenticated: true, body })
      onCreated()
    } catch (requestError) {
      setError(requestError.message || 'Unable to create this lease. Please try again.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <form className="management-form" onSubmit={handleSubmit} noValidate aria-labelledby="lease-form-title">
      <div className="management-form-heading">
        <h3 id="lease-form-title">Create lease</h3>
        <button className="text-button" type="button" onClick={onCancel} disabled={isSaving}>Cancel</button>
      </div>
      {error && <div className="form-error" role="alert">{error}</div>}
      {(tenants.length === 0 || activeUnits.length === 0) && (
        <p className="form-guidance">
          {tenants.length === 0 && activeUnits.length === 0
            ? 'Register a tenant and add an active unit before creating a lease.'
            : tenants.length === 0
              ? 'Register a tenant before creating a lease.'
              : 'Add an active unit to a property before creating a lease.'}
        </p>
      )}
      <div className="management-fields lease-fields">
        <div className="field-group">
          <label htmlFor="lease-tenant">Tenant</label>
          <select id="lease-tenant" value={tenantId} disabled={isSaving || tenants.length === 0} required onChange={(event) => setTenantId(event.target.value)}>
            <option value="">Select a tenant</option>
            {tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.full_name} — {tenant.email}</option>)}
          </select>
        </div>
        <div className="field-group">
          <label htmlFor="lease-unit">Active unit</label>
          <select id="lease-unit" value={unitId} disabled={isSaving || activeUnits.length === 0} required onChange={(event) => setUnitId(event.target.value)}>
            <option value="">Select a unit</option>
            {activeUnits.map((unit) => {
              const property = properties.find((item) => item.id === unit.property_id)
              return <option key={unit.id} value={unit.id}>{property?.name || 'Property'} — Unit {unit.unit_number}</option>
            })}
          </select>
        </div>
        <div className="field-group">
          <label htmlFor="lease-start-date">Start date</label>
          <input id="lease-start-date" type="date" value={startDate} disabled={isSaving} required onChange={(event) => setStartDate(event.target.value)} />
        </div>
        <div className="field-group">
          <label htmlFor="lease-end-date">End date <span className="optional-label">Optional</span></label>
          <input id="lease-end-date" type="date" min={startDate || undefined} value={endDate} disabled={isSaving} onChange={(event) => setEndDate(event.target.value)} />
        </div>
        <div className="field-group">
          <label htmlFor="lease-monthly-rent">Agreed monthly rent (KES)</label>
          <input id="lease-monthly-rent" type="text" inputMode="decimal" placeholder="e.g. 15000.00" value={monthlyRent} disabled={isSaving} required onChange={(event) => setMonthlyRent(event.target.value)} />
        </div>
      </div>
      {hasOverlap && (
        <p className="form-warning" role="status">
          An active lease overlaps these dates for this unit. The lease can be saved inactive, but the backend will reject activation while the overlap remains.
        </p>
      )}
      <div className="management-form-actions">
        <button className="primary-button compact-button" type="submit" disabled={isSaving || tenants.length === 0 || activeUnits.length === 0}>
          {isSaving ? 'Saving…' : 'Create lease'}
        </button>
      </div>
    </form>
  )
}

function leaseOverlaps(lease, startDate, endDate) {
  const startsBeforeNewEnd = !endDate || lease.start_date <= endDate
  const endsAfterNewStart = !lease.end_date || lease.end_date >= startDate
  return startsBeforeNewEnd && endsAfterNewStart
}

function LeasesPage() {
  const [data, setData] = useState({ loading: true, leases: [], tenants: [], properties: [], units: [], error: '' })
  const [retryCount, setRetryCount] = useState(0)
  const [selectedLeaseId, setSelectedLeaseId] = useState(null)
  const [leaseDetails, setLeaseDetails] = useState({ loading: false, lease: null, error: '' })
  const [detailRetry, setDetailRetry] = useState(0)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [isEnding, setIsEnding] = useState(false)
  const [endDate, setEndDate] = useState('')
  const [actionState, setActionState] = useState({ busy: false, error: '' })

  useEffect(() => {
    let isCurrent = true
    async function fetchPageData() {
      setData((current) => ({ ...current, loading: true, error: '' }))
      try {
        const [leaseResult, tenantResult, propertyResult] = await Promise.all([
          apiRequest('/api/leases', { authenticated: true }),
          apiRequest('/api/tenants', { authenticated: true }),
          apiRequest('/api/properties', { authenticated: true }),
        ])
        if (!Array.isArray(leaseResult?.leases) || !Array.isArray(tenantResult?.tenants) || !Array.isArray(propertyResult?.properties)) {
          throw new Error('Lease information could not be read. Please try again.')
        }
        const unitResults = await Promise.all(propertyResult.properties.map(async (property) => {
          const result = await apiRequest(`/api/properties/${encodeURIComponent(property.id)}/units`, { authenticated: true })
          if (!Array.isArray(result?.units)) throw new Error('Unit information could not be read. Please try again.')
          return result.units
        }))
        if (isCurrent) {
          setData({
            loading: false,
            leases: leaseResult.leases,
            tenants: tenantResult.tenants,
            properties: propertyResult.properties,
            units: unitResults.flat(),
            error: '',
          })
        }
      } catch (error) {
        if (isCurrent) setData((current) => ({ ...current, loading: false, error: error.message || 'Unable to load lease information.' }))
      }
    }
    fetchPageData()
    return () => { isCurrent = false }
  }, [retryCount])

  useEffect(() => {
    if (selectedLeaseId === null) return undefined
    let isCurrent = true
    async function fetchLease() {
      setLeaseDetails({ loading: true, lease: null, error: '' })
      try {
        const result = await apiRequest(`/api/leases/${encodeURIComponent(selectedLeaseId)}`, { authenticated: true })
        if (!result?.lease) throw new Error('Lease details could not be read. Please try again.')
        if (isCurrent) setLeaseDetails({ loading: false, lease: result.lease, error: '' })
      } catch (error) {
        if (isCurrent) setLeaseDetails({ loading: false, lease: null, error: error.message || 'Unable to load lease details.' })
      }
    }
    fetchLease()
    return () => { isCurrent = false }
  }, [selectedLeaseId, detailRetry])

  function leaseCreated() {
    setShowCreateForm(false)
    setRetryCount((count) => count + 1)
  }

  async function updateLease(action, body) {
    if (!leaseDetails.lease) return
    setActionState({ busy: true, error: '' })
    try {
      await apiRequest(`/api/leases/${encodeURIComponent(leaseDetails.lease.id)}/${action}`, {
        method: 'POST',
        authenticated: true,
        ...(body ? { body } : {}),
      })
      setIsEnding(false)
      setRetryCount((count) => count + 1)
      setDetailRetry((count) => count + 1)
    } catch (error) {
      setActionState({ busy: false, error: error.message || 'Unable to update this lease.' })
      return
    }
    setActionState({ busy: false, error: '' })
  }

  const today = localDateString(new Date())
  const tenantById = new Map(data.tenants.map((tenant) => [tenant.id, tenant]))
  const unitById = new Map(data.units.map((unit) => [unit.id, unit]))
  const propertyById = new Map(data.properties.map((property) => [property.id, property]))
  const selectedLease = leaseDetails.lease
  const selectedUnit = selectedLease ? unitById.get(selectedLease.unit_id) : null
  const selectedProperty = selectedUnit ? propertyById.get(selectedUnit.property_id) : null
  const activeOverlap = selectedLease && !selectedLease.is_active && data.leases.some((lease) => (
    lease.is_active && lease.unit_id === selectedLease.unit_id && leaseOverlaps(lease, selectedLease.start_date, selectedLease.end_date)
  ))
  const pastScheduledEnd = Boolean(selectedLease?.end_date && selectedLease.end_date < today)
  const cannotActivateReason = selectedLease?.is_active
    ? ''
    : !selectedUnit?.is_active
      ? 'This unit is inactive and cannot be leased.'
      : pastScheduledEnd
        ? 'A lease with a past end date cannot be activated.'
        : activeOverlap
          ? 'This lease overlaps another active lease for the unit.'
          : ''

  if (selectedLeaseId !== null) {
    return (
      <section className="management-page" aria-labelledby="lease-detail-heading">
        <button className="back-button" type="button" onClick={() => { setSelectedLeaseId(null); setIsEnding(false); setActionState({ busy: false, error: '' }) }}>
          <span aria-hidden="true">←</span> All leases
        </button>
        {leaseDetails.loading ? (
          <div className="overview-message" role="status" aria-live="polite"><span className="loading-dot" aria-hidden="true" /> Loading lease details…</div>
        ) : leaseDetails.error ? (
          <div className="overview-message overview-error" role="alert">
            <div><h4>Lease details could not be loaded</h4><p>{leaseDetails.error}</p></div>
            <button className="retry-button" type="button" onClick={() => setDetailRetry((count) => count + 1)}>Try again</button>
          </div>
        ) : selectedLease && (
          <>
            <div className="management-page-heading detail-heading">
              <div>
                <p className="eyebrow">Lease record</p>
                <h2 id="lease-detail-heading">{tenantById.get(selectedLease.tenant_id)?.full_name || 'Tenant unavailable'}</h2>
                <p>{selectedProperty?.name || 'Property unavailable'}{selectedUnit ? ` · Unit ${selectedUnit.unit_number}` : ''}</p>
              </div>
              <span className={`status-pill lease-status${selectedLease.is_active ? ' is-active' : ''}`}>
                {selectedLease.is_active ? 'Active' : 'Inactive'}
              </span>
            </div>
            <dl className="lease-detail-card">
              <div><dt>Tenant</dt><dd>{tenantById.get(selectedLease.tenant_id)?.full_name || 'Unavailable'}</dd></div>
              <div><dt>Property and unit</dt><dd>{selectedProperty?.name || 'Unavailable'}{selectedUnit ? ` · Unit ${selectedUnit.unit_number}` : ''}</dd></div>
              <div><dt>Start date</dt><dd>{selectedLease.start_date}</dd></div>
              <div><dt>End date</dt><dd>{selectedLease.end_date || 'No scheduled end date'}</dd></div>
              <div><dt>Agreed monthly rent</dt><dd>{formatKes(selectedLease.monthly_rent)}</dd></div>
              <div><dt>Status</dt><dd>{selectedLease.is_active ? 'Active' : 'Inactive'}</dd></div>
            </dl>
            {actionState.error && <div className="form-error lease-action-error" role="alert">{actionState.error}</div>}
            {selectedLease.is_active ? (
              selectedLease.start_date <= today ? (
                isEnding ? (
                  <form className="management-form lease-end-form" onSubmit={(event) => {
                    event.preventDefault()
                    const maximumDate = selectedLease.end_date && selectedLease.end_date < today ? selectedLease.end_date : today
                    if (!endDate || endDate < selectedLease.start_date || endDate > maximumDate) {
                      setActionState({ busy: false, error: 'End date must be on or after the lease start and no later than today or the scheduled end date.' })
                      return
                    }
                    updateLease('end', { end_date: endDate })
                  }}>
                    <div className="management-form-heading"><h3>End active lease</h3></div>
                    <div className="field-group">
                      <label htmlFor="lease-effective-end">Effective end date</label>
                      <input id="lease-effective-end" type="date" min={selectedLease.start_date} max={selectedLease.end_date && selectedLease.end_date < today ? selectedLease.end_date : today} value={endDate} disabled={actionState.busy} required onChange={(event) => setEndDate(event.target.value)} />
                    </div>
                    <div className="management-form-actions">
                      <button className="text-button" type="button" disabled={actionState.busy} onClick={() => setIsEnding(false)}>Cancel</button>
                      <button className="primary-button compact-button" type="submit" disabled={actionState.busy}>{actionState.busy ? 'Saving…' : 'Confirm end'}</button>
                    </div>
                  </form>
                ) : (
                  <div className="lease-actions">
                    <button className="secondary-button compact-button" type="button" disabled={actionState.busy} onClick={() => {
                      const defaultDate = selectedLease.end_date && selectedLease.end_date < today ? selectedLease.end_date : today
                      setEndDate(defaultDate)
                      setActionState({ busy: false, error: '' })
                      setIsEnding(true)
                    }}>End lease</button>
                  </div>
                )
              ) : (
                <p className="form-guidance">This lease starts in the future and cannot be ended before its start date.</p>
              )
            ) : (
              <div className="lease-actions">
                {cannotActivateReason ? (
                  <p className="form-guidance">{cannotActivateReason}</p>
                ) : null}
                <button className="primary-button compact-button" type="button" disabled={actionState.busy || Boolean(cannotActivateReason)} onClick={() => updateLease('activate')}>
                  {actionState.busy ? 'Saving…' : 'Activate lease'}
                </button>
              </div>
            )}
          </>
        )}
      </section>
    )
  }

  return (
    <section className="management-page" aria-labelledby="leases-page-heading">
      <div className="management-page-heading">
        <div>
          <p className="eyebrow">Agreements</p>
          <h2 id="leases-page-heading">Leases</h2>
          <p>Review tenancy periods, agreed rent, and lease status.</p>
        </div>
        <button className="primary-button compact-button" type="button" onClick={() => setShowCreateForm(true)}>Create lease</button>
      </div>
      {showCreateForm && (
        <LeaseForm
          tenants={data.tenants}
          properties={data.properties}
          units={data.units}
          leases={data.leases}
          onCancel={() => setShowCreateForm(false)}
          onCreated={leaseCreated}
        />
      )}
      {data.loading ? (
        <div className="overview-message" role="status" aria-live="polite"><span className="loading-dot" aria-hidden="true" /> Loading leases and available units…</div>
      ) : data.error ? (
        <div className="overview-message overview-error" role="alert">
          <div><h4>Lease information could not be loaded</h4><p>{data.error}</p></div>
          <button className="retry-button" type="button" onClick={() => setRetryCount((count) => count + 1)}>Try again</button>
        </div>
      ) : data.leases.length === 0 ? (
        <div className="overview-empty compact-empty">
          <h4>No leases yet</h4>
          <p>Created leases will appear here. A new lease remains inactive until you activate it.</p>
        </div>
      ) : (
        <ul className="lease-list">
          {data.leases.map((lease) => {
            const tenant = tenantById.get(lease.tenant_id)
            const unit = unitById.get(lease.unit_id)
            const property = unit ? propertyById.get(unit.property_id) : null
            return (
              <li key={lease.id}>
                <button className="lease-list-card" type="button" onClick={() => setSelectedLeaseId(lease.id)}>
                  <span className={`lease-indicator${lease.is_active ? ' is-active' : ''}`} aria-hidden="true" />
                  <span className="lease-list-main">
                    <strong>{tenant?.full_name || 'Tenant unavailable'}</strong>
                    <span>{property?.name || 'Property unavailable'}{unit ? ` · Unit ${unit.unit_number}` : ''}</span>
                  </span>
                  <span className="lease-list-dates">{lease.start_date}{lease.end_date ? ` – ${lease.end_date}` : ' – No end date'}</span>
                  <span className="lease-list-rent">{formatKes(lease.monthly_rent)}<small>monthly</small></span>
                  <span className={`status-pill${lease.is_active ? ' is-active' : ''}`}>{lease.is_active ? 'Active' : 'Inactive'}</span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

function localDateString(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

const MAX_MONEY_CENTS = 999999999999n

function moneyToCents(value) {
  const text = String(value).trim()
  if (!/^\d+(?:\.\d{1,2})?$/.test(text)) return null
  const [whole, fraction = ''] = text.split('.')
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))
  return cents <= MAX_MONEY_CENTS ? cents : null
}

function centsToMoney(cents) {
  return `${cents / 100n}.${String(cents % 100n).padStart(2, '0')}`
}

function invoicePaymentProgress(invoice) {
  const total = moneyToCents(invoice.total_amount)
  const paid = moneyToCents(invoice.paid_amount)
  const outstanding = moneyToCents(invoice.outstanding_balance)
  if (total === 0n && outstanding === 0n) return 'No balance due'
  if (outstanding === 0n) return 'Fully paid'
  if (paid > 0n) return 'Partially paid'
  return 'Unpaid'
}

function invoiceChargeLabel(category) {
  return category.charAt(0).toUpperCase() + category.slice(1)
}

function InvoiceForm({ leases, tenants, properties, units, invoices, onCancel, onCreated }) {
  const [leaseId, setLeaseId] = useState('')
  const [purpose, setPurpose] = useState('rent')
  const [periodStart, setPeriodStart] = useState('')
  const [periodEnd, setPeriodEnd] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [charges, setCharges] = useState([{ key: 1, category: 'rent', description: 'Rent', amount: '' }])
  const [nextChargeKey, setNextChargeKey] = useState(2)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')

  const tenantById = new Map(tenants.map((tenant) => [tenant.id, tenant]))
  const unitById = new Map(units.map((unit) => [unit.id, unit]))
  const propertyById = new Map(properties.map((property) => [property.id, property]))
  const eligibleLeases = leases.filter((lease) => lease.is_active)
  const selectedLease = eligibleLeases.find((lease) => String(lease.id) === leaseId)
  const duplicatePurpose = Boolean(selectedLease && periodStart && periodEnd && invoices.some((invoice) => (
    invoice.lease_id === selectedLease.id && invoice.period_start === periodStart && invoice.period_end === periodEnd && invoice.purpose === purpose
  )))

  function updateCharge(key, updates) {
    setCharges((current) => current.map((charge) => charge.key === key ? { ...charge, ...updates } : charge))
  }

  function addCharge() {
    if (purpose === 'utilities') return
    setCharges((current) => [...current, { key: nextChargeKey, category: purpose, description: '', amount: '' }])
    setNextChargeKey((key) => key + 1)
  }

  function changePurpose(nextPurpose) {
    setPurpose(nextPurpose)
    setCharges([{
      key: nextChargeKey,
      category: nextPurpose,
      description: '',
      amount: '',
      ...(nextPurpose === 'utilities' ? { water: '', garbage: '' } : {}),
    }])
    setNextChargeKey((key) => key + 1)
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    if (!selectedLease) {
      setError('Select an active lease for this invoice.')
      return
    }
    if (!periodStart || !periodEnd || !dueDate) {
      setError('Enter the billing period start, end, and due dates.')
      return
    }
    if (periodEnd < periodStart) {
      setError('Billing period end cannot be before its start.')
      return
    }
    if (duplicatePurpose) {
      setError(`A ${purpose} invoice already exists for this lease and billing period.`)
      return
    }
    if (!charges.length) {
      setError('Add at least one invoice charge.')
      return
    }

    const payloadCharges = []
    for (const [index, charge] of charges.entries()) {
      const description = charge.description.trim()
      if (description.length > 255) {
        setError(`Charge ${index + 1} description must be at most 255 characters.`)
        return
      }
      if (charge.category === 'utilities') {
        const waterCents = moneyToCents(charge.water || '')
        const garbageCents = moneyToCents(charge.garbage || '')
        if (waterCents === null || garbageCents === null) {
          setError(`Enter valid water and garbage amounts for charge ${index + 1}, each with no more than two decimal places.`)
          return
        }
        const totalCents = waterCents + garbageCents
        if (totalCents > MAX_MONEY_CENTS) {
          setError(`Utilities charge ${index + 1} is too large.`)
          return
        }
        payloadCharges.push({
          category: 'utilities',
          amount: centsToMoney(totalCents),
          description: description || null,
          utility_breakdowns: [
            { category: 'water', amount: centsToMoney(waterCents) },
            { category: 'garbage', amount: centsToMoney(garbageCents) },
          ],
        })
      } else {
        const amountCents = moneyToCents(charge.amount || '')
        if (amountCents === null) {
          setError(`Enter a valid ${charge.category} amount for charge ${index + 1}, with no more than two decimal places.`)
          return
        }
        payloadCharges.push({
          category: charge.category,
          amount: centsToMoney(amountCents),
          description: description || null,
        })
      }
    }

    const body = {
      lease_id: Number(leaseId),
      period_start: periodStart,
      period_end: periodEnd,
      due_date: dueDate,
      purpose,
      charges: payloadCharges,
    }
    setIsSaving(true)
    try {
      const result = await apiRequest('/api/invoices', { method: 'POST', authenticated: true, body })
      onCreated(result.invoice)
    } catch (requestError) {
      setError(requestError.message || 'Unable to create this invoice. Please try again.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <form className="management-form invoice-form" onSubmit={handleSubmit} noValidate aria-labelledby="invoice-form-title">
      <div className="management-form-heading">
        <h3 id="invoice-form-title">Create draft invoice</h3>
        <button className="text-button" type="button" onClick={onCancel} disabled={isSaving}>Cancel</button>
      </div>
      {error && <div className="form-error" role="alert">{error}</div>}
      {eligibleLeases.length === 0 && <p className="form-guidance">Invoices can only be created for active leases. Activate an eligible lease first.</p>}
      <div className="management-fields invoice-fields">
        <div className="field-group">
          <label htmlFor="invoice-purpose">Invoice purpose</label>
          <select id="invoice-purpose" value={purpose} disabled={isSaving} onChange={(event) => changePurpose(event.target.value)}>
            <option value="rent">Rent</option>
            <option value="utilities">Utilities</option>
            <option value="other">Other</option>
          </select>
        </div>
        <div className="field-group">
          <label htmlFor="invoice-lease">Active lease</label>
          <select id="invoice-lease" value={leaseId} disabled={isSaving || eligibleLeases.length === 0} required onChange={(event) => setLeaseId(event.target.value)}>
            <option value="">Select an active lease</option>
            {eligibleLeases.map((lease) => {
              const tenant = tenantById.get(lease.tenant_id)
              const unit = unitById.get(lease.unit_id)
              const property = unit ? propertyById.get(unit.property_id) : null
              return <option key={lease.id} value={lease.id}>{tenant?.full_name || 'Tenant'} · {property?.name || 'Property'} / {unit?.unit_number || 'Unit'}</option>
            })}
          </select>
        </div>
        <div className="field-group">
          <label htmlFor="invoice-period-start">Billing period start</label>
          <input id="invoice-period-start" type="date" value={periodStart} disabled={isSaving} required onChange={(event) => setPeriodStart(event.target.value)} />
        </div>
        <div className="field-group">
          <label htmlFor="invoice-period-end">Billing period end</label>
          <input id="invoice-period-end" type="date" min={periodStart || undefined} value={periodEnd} disabled={isSaving} required onChange={(event) => setPeriodEnd(event.target.value)} />
        </div>
        <div className="field-group">
          <label htmlFor="invoice-due-date">Due date</label>
          <input id="invoice-due-date" type="date" value={dueDate} disabled={isSaving} required onChange={(event) => setDueDate(event.target.value)} />
        </div>
      </div>
      {duplicatePurpose && <p className="form-warning" role="status">A {purpose} invoice already exists for this lease and exact billing period.</p>}

      <div className="invoice-charge-heading">
        <div><h4>Charges</h4><p>{purpose === 'utilities' ? 'Water and garbage form one combined utilities charge.' : `Add one or more ${purpose} charges.`}</p></div>
        {purpose !== 'utilities' && <button className="secondary-button compact-button" type="button" onClick={addCharge} disabled={isSaving}>Add charge</button>}
      </div>
      <div className="invoice-charge-list">
        {charges.map((charge, index) => {
          const waterCents = charge.category === 'utilities' ? moneyToCents(charge.water || '') : null
          const garbageCents = charge.category === 'utilities' ? moneyToCents(charge.garbage || '') : null
          const combinedCents = waterCents !== null && garbageCents !== null ? waterCents + garbageCents : null
          return (
            <fieldset className="invoice-charge-row" key={charge.key}>
              <legend>Charge {index + 1}</legend>
              <div className={`invoice-charge-controls${charge.category === 'utilities' ? ' utilities-charge-controls' : ''}`}>
                <div className="field-group">
                  <label htmlFor={`charge-category-${charge.key}`}>Category</label>
                  <select id={`charge-category-${charge.key}`} value={charge.category} disabled={isSaving} onChange={(event) => {
                    const category = event.target.value
                    updateCharge(charge.key, category === 'utilities'
                      ? { category, amount: '', water: '', garbage: '' }
                      : { category, amount: '', water: undefined, garbage: undefined })
                  }}>
                    <option value={purpose}>{invoiceChargeLabel(purpose)}</option>
                  </select>
                </div>
                <div className="field-group charge-description-field">
                  <label htmlFor={`charge-description-${charge.key}`}>Description <span className="optional-label">Optional</span></label>
                  <input id={`charge-description-${charge.key}`} value={charge.description} maxLength={255} disabled={isSaving} onChange={(event) => updateCharge(charge.key, { description: event.target.value })} />
                </div>
                {charge.category === 'utilities' ? (
                  <>
                    <div className="field-group">
                      <label htmlFor={`charge-water-${charge.key}`}>Water (KES)</label>
                      <input id={`charge-water-${charge.key}`} type="text" inputMode="decimal" placeholder="0.00" value={charge.water} disabled={isSaving} onChange={(event) => updateCharge(charge.key, { water: event.target.value })} />
                    </div>
                    <div className="field-group">
                      <label htmlFor={`charge-garbage-${charge.key}`}>Garbage (KES)</label>
                      <input id={`charge-garbage-${charge.key}`} type="text" inputMode="decimal" placeholder="0.00" value={charge.garbage} disabled={isSaving} onChange={(event) => updateCharge(charge.key, { garbage: event.target.value })} />
                    </div>
                    <div className="utilities-total">
                      <span>Combined utilities charge</span>
                      <strong>{combinedCents === null ? 'Enter both amounts' : formatKes(centsToMoney(combinedCents))}</strong>
                    </div>
                  </>
                ) : (
                  <div className="field-group">
                    <label htmlFor={`charge-amount-${charge.key}`}>Amount (KES)</label>
                    <input id={`charge-amount-${charge.key}`} type="text" inputMode="decimal" placeholder="e.g. 15000.00" value={charge.amount} disabled={isSaving} onChange={(event) => updateCharge(charge.key, { amount: event.target.value })} />
                  </div>
                )}
                <button className="remove-charge-button" type="button" disabled={isSaving || charges.length === 1 || purpose === 'utilities'} aria-label={`Remove charge ${index + 1}`} onClick={() => setCharges((current) => current.filter((item) => item.key !== charge.key))}>Remove</button>
              </div>
            </fieldset>
          )
        })}
      </div>
      <div className="management-form-actions">
        <button className="primary-button compact-button" type="submit" disabled={isSaving || eligibleLeases.length === 0 || duplicatePurpose}>
          {isSaving ? 'Saving…' : 'Save draft invoice'}
        </button>
      </div>
    </form>
  )
}

function currentBillingMonth() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

function readingToThousandths(value) {
  const text = String(value).trim()
  if (!/^\d+(?:\.\d{1,3})?$/.test(text)) return null
  const [whole, fraction = ''] = text.split('.')
  return BigInt(whole) * 1000n + BigInt(fraction.padEnd(3, '0'))
}

function MeterReadingAndBillingPanel({ properties, units, onGenerated, onReviewInvoice }) {
  const [billingMonth, setBillingMonth] = useState(currentBillingMonth)
  const [propertyId, setPropertyId] = useState('')
  const [rateDraft, setRateDraft] = useState({ water_rate: '', garbage_fee: '' })
  const [readings, setReadings] = useState({})
  const [isLoading, setIsLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [reload, setReload] = useState(0)
  const [savingRate, setSavingRate] = useState(false)
  const [rateError, setRateError] = useState('')
  const [savingUnit, setSavingUnit] = useState(null)
  const [readingErrors, setReadingErrors] = useState({})
  const [isGenerating, setIsGenerating] = useState(false)
  const [generationError, setGenerationError] = useState('')
  const [generationResult, setGenerationResult] = useState(null)

  useEffect(() => {
    if (!propertyId && properties.length) setPropertyId(String(properties[0].id))
  }, [propertyId, properties])

  useEffect(() => {
    if (!propertyId) {
      setReadings({})
      setLoadError('')
      return undefined
    }
    let isCurrent = true
    async function loadUtilityData() {
      setIsLoading(true)
      setLoadError('')
      try {
        const [settingsResult, readingResult] = await Promise.all([
          apiRequest(`/api/properties/${encodeURIComponent(propertyId)}/utility-settings`, { authenticated: true }),
          apiRequest(`/api/properties/${encodeURIComponent(propertyId)}/water-readings?billing_month=${encodeURIComponent(billingMonth)}`, { authenticated: true }),
        ])
        if (!settingsResult?.settings || !Array.isArray(readingResult?.readings)) {
          throw new Error('Utility information could not be read. Please try again.')
        }
        if (isCurrent) {
          setRateDraft({ water_rate: settingsResult.settings.water_rate, garbage_fee: settingsResult.settings.garbage_fee })
          setReadings(Object.fromEntries(readingResult.readings.map((reading) => [reading.unit_id, reading])))
        }
      } catch (error) {
        if (isCurrent) setLoadError(error.message || 'Unable to load utility information.')
      } finally {
        if (isCurrent) setIsLoading(false)
      }
    }
    loadUtilityData()
    return () => { isCurrent = false }
  }, [propertyId, billingMonth, reload])

  const propertyUnits = units.filter((unit) => String(unit.property_id) === propertyId)

  async function saveRates(event) {
    event.preventDefault()
    setRateError('')
    if (moneyToCents(rateDraft.water_rate) === null || moneyToCents(rateDraft.garbage_fee) === null) {
      setRateError('Enter non-negative water and garbage rates with no more than two decimal places.')
      return
    }
    setSavingRate(true)
    try {
      const result = await apiRequest(`/api/properties/${encodeURIComponent(propertyId)}/utility-settings`, {
        method: 'PATCH', authenticated: true, body: rateDraft,
      })
      setRateDraft({ water_rate: result.settings.water_rate, garbage_fee: result.settings.garbage_fee })
    } catch (error) {
      setRateError(error.message || 'Unable to save utility rates.')
    } finally {
      setSavingRate(false)
    }
  }

  async function saveReading(unit) {
    const reading = readings[unit.id] || {}
    setReadingErrors((current) => ({ ...current, [unit.id]: '' }))
    const previousValue = readingToThousandths(reading.previous_reading || '')
    const currentValue = readingToThousandths(reading.current_reading || '')
    if (previousValue === null || currentValue === null) {
      setReadingErrors((current) => ({ ...current, [unit.id]: 'Enter both readings with up to three decimal places.' }))
      return
    }
    if (currentValue < previousValue) {
      setReadingErrors((current) => ({ ...current, [unit.id]: 'Current reading cannot be less than the previous reading.' }))
      return
    }
    setSavingUnit(unit.id)
    try {
      const result = await apiRequest(`/api/properties/${encodeURIComponent(propertyId)}/units/${encodeURIComponent(unit.id)}/water-reading`, {
        method: 'PUT', authenticated: true,
        body: { billing_month: billingMonth, previous_reading: reading.previous_reading, current_reading: reading.current_reading },
      })
      setReadings((current) => ({ ...current, [unit.id]: result.reading }))
    } catch (error) {
      setReadingErrors((current) => ({ ...current, [unit.id]: error.message || 'Unable to save this reading.' }))
    } finally {
      setSavingUnit(null)
    }
  }

  async function generateDrafts() {
    setGenerationError('')
    setGenerationResult(null)
    setIsGenerating(true)
    try {
      const result = await apiRequest('/api/invoices/generate-monthly', {
        method: 'POST', authenticated: true, body: { billing_month: billingMonth },
      })
      setGenerationResult(result)
      onGenerated()
    } catch (error) {
      setGenerationError(error.message || 'Unable to generate monthly drafts.')
    } finally {
      setIsGenerating(false)
    }
  }

  return (
    <section className="utility-billing-panel" aria-labelledby="utility-billing-heading">
      <div className="utility-billing-heading">
        <div><p className="eyebrow">Monthly billing</p><h3 id="utility-billing-heading">Meter readings and draft generation</h3><p>Save unit readings, then prepare rent and utility drafts for a calendar month.</p></div>
        <div className="field-group billing-month-field"><label htmlFor="billing-month">Billing month</label><input id="billing-month" type="month" value={billingMonth} disabled={isGenerating} onChange={(event) => { setBillingMonth(event.target.value); setGenerationResult(null) }} /></div>
      </div>

      <form className="utility-rates-form" onSubmit={saveRates}>
        <div className="utility-property-field field-group">
          <label htmlFor="utility-property">Property rates</label>
          <select id="utility-property" value={propertyId} disabled={isLoading || properties.length === 0} onChange={(event) => setPropertyId(event.target.value)}>
            {properties.length === 0 ? <option value="">No properties available</option> : properties.map((property) => <option key={property.id} value={property.id}>{property.name}</option>)}
          </select>
        </div>
        <div className="field-group"><label htmlFor="water-rate">Water per unit (KES)</label><input id="water-rate" type="text" inputMode="decimal" value={rateDraft.water_rate} disabled={isLoading || savingRate || !propertyId} onChange={(event) => setRateDraft((current) => ({ ...current, water_rate: event.target.value }))} /></div>
        <div className="field-group"><label htmlFor="garbage-fee">Garbage per unit/month (KES)</label><input id="garbage-fee" type="text" inputMode="decimal" value={rateDraft.garbage_fee} disabled={isLoading || savingRate || !propertyId} onChange={(event) => setRateDraft((current) => ({ ...current, garbage_fee: event.target.value }))} /></div>
        <button className="secondary-button compact-button" type="submit" disabled={isLoading || savingRate || !propertyId}>{savingRate ? 'Saving…' : 'Save rates'}</button>
      </form>
      {rateError && <div className="form-error utility-inline-error" role="alert">{rateError}</div>}

      {isLoading ? (
        <div className="overview-message" role="status" aria-live="polite"><span className="loading-dot" aria-hidden="true" /> Loading meter readings…</div>
      ) : loadError ? (
        <div className="overview-message overview-error" role="alert"><div><h4>Utility information could not be loaded</h4><p>{loadError}</p></div><button className="retry-button" type="button" onClick={() => setReload((count) => count + 1)}>Try again</button></div>
      ) : properties.length === 0 ? (
        <p className="form-guidance">Add a property and units before entering meter readings. Only active units with active leases are billed.</p>
      ) : propertyUnits.length === 0 ? (
        <div className="overview-empty compact-empty"><h4>No units in this property</h4><p>Add a unit before recording meter readings. Only active units with active leases are billed.</p></div>
      ) : (
        <div className="meter-reading-table-wrap">
          <div className="meter-reading-table-heading"><div><h4>Water meter readings</h4><p>For {billingMonth}; saved entries can be corrected until an invoice exists for that period.</p></div><span>Readings may include three decimal places.</span></div>
          <div className="meter-reading-list">
            {propertyUnits.map((unit) => {
              const reading = readings[unit.id] || { previous_reading: '', current_reading: '' }
              return <div className="meter-reading-row" key={unit.id}>
                <strong>Unit {unit.unit_number}<small className="meter-unit-status">{unit.is_active ? 'Active unit' : 'Inactive unit'}</small></strong>
                <div className="field-group"><label htmlFor={`previous-reading-${unit.id}`}>Previous reading</label><input id={`previous-reading-${unit.id}`} type="text" inputMode="decimal" placeholder="0.000" value={reading.previous_reading} disabled={savingUnit === unit.id} onChange={(event) => setReadings((current) => ({ ...current, [unit.id]: { ...reading, previous_reading: event.target.value } }))} /></div>
                <div className="field-group"><label htmlFor={`current-reading-${unit.id}`}>Current reading</label><input id={`current-reading-${unit.id}`} type="text" inputMode="decimal" placeholder="0.000" value={reading.current_reading} disabled={savingUnit === unit.id} onChange={(event) => setReadings((current) => ({ ...current, [unit.id]: { ...reading, current_reading: event.target.value } }))} /></div>
                <button className="secondary-button compact-button" type="button" disabled={savingUnit === unit.id} onClick={() => saveReading(unit)}>{savingUnit === unit.id ? 'Saving…' : reading.id ? 'Update reading' : 'Save reading'}</button>
                {readingErrors[unit.id] && <div className="form-error meter-reading-error" role="alert">{readingErrors[unit.id]}</div>}
              </div>
            })}
          </div>
        </div>
      )}

      <div className="monthly-generation-actions">
        <div><strong>Generate monthly drafts</strong><span>Uses active leases and units, current lease rent, saved readings, and property rates.</span></div>
        <button className="primary-button compact-button" type="button" disabled={isGenerating || !billingMonth} onClick={generateDrafts}>{isGenerating ? 'Generating drafts…' : 'Generate draft invoices'}</button>
      </div>
      {generationError && <div className="form-error utility-inline-error" role="alert">{generationError}<button className="text-button" type="button" disabled={isGenerating} onClick={generateDrafts}>Retry</button></div>}
      {generationResult && (
        <div className="generation-summary" role="status" aria-live="polite">
          <div><h4>Draft generation complete for {generationResult.billing_month}</h4><p>{generationResult.created_count} created · {generationResult.already_existing_count} already existed · {generationResult.needs_reading_count} need meter attention.</p></div>
          {generationResult.created_invoices.length > 0 && <div className="generation-summary-group"><strong>Created drafts</strong><ul>{generationResult.created_invoices.map((invoice) => <li key={invoice.id}><button className="text-button" type="button" onClick={() => onReviewInvoice(invoice.id, invoice.purpose)}>Review {invoice.purpose} draft · {formatKes(invoice.total_amount)}</button></li>)}</ul></div>}
          {generationResult.already_existing.length > 0 && <div className="generation-summary-group"><strong>Already existing</strong><ul>{generationResult.already_existing.map((invoice) => <li key={invoice.id}><button className="text-button" type="button" onClick={() => onReviewInvoice(invoice.id, invoice.purpose)}>Review {invoice.purpose} invoice</button></li>)}</ul></div>}
          {generationResult.needs_readings.length > 0 && <div className="generation-summary-group generation-needs-readings"><strong>Readings needed</strong><ul>{generationResult.needs_readings.map((item) => <li key={`${item.unit_id}-${item.reason}`}>{item.property_name} · Unit {item.unit_number}: {item.reason === 'missing' ? 'enter readings for this month' : item.reason === 'invalid' ? 'correct the saved meter readings' : 'calculated utility amount exceeds the invoice limit'}</li>)}</ul></div>}
        </div>
      )}
    </section>
  )
}

function useInvoiceWorkspaceData() {
  const [data, setData] = useState({ loading: true, invoices: [], leases: [], tenants: [], properties: [], units: [], error: '' })
  const [retryCount, setRetryCount] = useState(0)

  useEffect(() => {
    let isCurrent = true
    async function fetchPageData() {
      setData((current) => ({ ...current, loading: true, error: '' }))
      try {
        const [invoiceResult, leaseResult, tenantResult, propertyResult] = await Promise.all([
          apiRequest('/api/invoices', { authenticated: true }),
          apiRequest('/api/leases', { authenticated: true }),
          apiRequest('/api/tenants', { authenticated: true }),
          apiRequest('/api/properties', { authenticated: true }),
        ])
        if (!Array.isArray(invoiceResult?.invoices) || !Array.isArray(leaseResult?.leases) || !Array.isArray(tenantResult?.tenants) || !Array.isArray(propertyResult?.properties)) {
          throw new Error('Invoice information could not be read. Please try again.')
        }
        const unitResults = await Promise.all(propertyResult.properties.map(async (property) => {
          const result = await apiRequest(`/api/properties/${encodeURIComponent(property.id)}/units`, { authenticated: true })
          if (!Array.isArray(result?.units)) throw new Error('Unit information could not be read. Please try again.')
          return result.units
        }))
        if (isCurrent) {
          setData({
            loading: false,
            invoices: invoiceResult.invoices,
            leases: leaseResult.leases,
            tenants: tenantResult.tenants,
            properties: propertyResult.properties,
            units: unitResults.flat(),
            error: '',
          })
        }
      } catch (error) {
        if (isCurrent) setData((current) => ({ ...current, loading: false, error: error.message || 'Unable to load invoice information.' }))
      }
    }
    fetchPageData()
    return () => { isCurrent = false }
  }, [retryCount])

  return { data, retry: () => setRetryCount((count) => count + 1) }
}

function MonthlyBillingPage({ onOpenInvoice }) {
  const { data, retry } = useInvoiceWorkspaceData()
  const [showCreateForm, setShowCreateForm] = useState(false)

  function invoiceCreated(invoice) {
    setShowCreateForm(false)
    retry()
    onOpenInvoice(invoice.id, invoice.purpose)
  }

  return (
    <section className="management-page" aria-labelledby="monthly-billing-page-heading">
      <div className="management-page-heading">
        <div>
          <p className="eyebrow">Billing operations</p>
          <h2 id="monthly-billing-page-heading">Monthly Billing</h2>
          <p>Set property utility rates, manage meter readings, and prepare monthly drafts.</p>
        </div>
        <button className="secondary-button compact-button" type="button" onClick={() => setShowCreateForm((visible) => !visible)}>
          {showCreateForm ? 'Close manual invoice' : 'Create manual invoice'}
        </button>
      </div>

      {data.loading ? (
        <div className="overview-message" role="status" aria-live="polite"><span className="loading-dot" aria-hidden="true" /> Loading billing information…</div>
      ) : data.error ? (
        <div className="overview-message overview-error" role="alert">
          <div><h4>Billing information could not be loaded</h4><p>{data.error}</p></div>
          <button className="retry-button" type="button" onClick={retry}>Try again</button>
        </div>
      ) : (
        <>
          <MeterReadingAndBillingPanel
            properties={data.properties}
            units={data.units}
            onGenerated={retry}
            onReviewInvoice={onOpenInvoice}
          />
          {showCreateForm && (
            <InvoiceForm
              leases={data.leases}
              tenants={data.tenants}
              properties={data.properties}
              units={data.units}
              invoices={data.invoices}
              onCancel={() => setShowCreateForm(false)}
              onCreated={invoiceCreated}
            />
          )}
        </>
      )}
    </section>
  )
}

function InvoicesPage({ purpose, selectedInvoiceId, setSelectedInvoiceId }) {
  const { data, retry } = useInvoiceWorkspaceData()
  const [invoiceDetails, setInvoiceDetails] = useState({ loading: false, invoice: null, error: '' })
  const [detailRetry, setDetailRetry] = useState(0)
  const [issueState, setIssueState] = useState({ busy: false, error: '' })

  useEffect(() => {
    if (selectedInvoiceId === null) return undefined
    let isCurrent = true
    async function fetchInvoice() {
      setInvoiceDetails({ loading: true, invoice: null, error: '' })
      try {
        const result = await apiRequest(`/api/invoices/${encodeURIComponent(selectedInvoiceId)}`, { authenticated: true })
        if (!result?.invoice) throw new Error('Invoice details could not be read. Please try again.')
        if (isCurrent) setInvoiceDetails({ loading: false, invoice: result.invoice, error: '' })
      } catch (error) {
        if (isCurrent) setInvoiceDetails({ loading: false, invoice: null, error: error.message || 'Unable to load invoice details.' })
      }
    }
    fetchInvoice()
    return () => { isCurrent = false }
  }, [selectedInvoiceId, detailRetry])

  async function issueInvoice() {
    if (!invoiceDetails.invoice || invoiceDetails.invoice.status !== 'draft') return
    setIssueState({ busy: true, error: '' })
    try {
      const result = await apiRequest(`/api/invoices/${encodeURIComponent(invoiceDetails.invoice.id)}/issue`, {
        method: 'POST',
        authenticated: true,
      })
      if (result?.invoice) setInvoiceDetails({ loading: false, invoice: result.invoice, error: '' })
      retry()
      setIssueState({ busy: false, error: '' })
    } catch (error) {
      setIssueState({ busy: false, error: error.message || 'Unable to issue this invoice.' })
    }
  }

  const leaseById = new Map(data.leases.map((lease) => [lease.id, lease]))
  const tenantById = new Map(data.tenants.map((tenant) => [tenant.id, tenant]))
  const unitById = new Map(data.units.map((unit) => [unit.id, unit]))
  const propertyById = new Map(data.properties.map((property) => [property.id, property]))
  const selectedInvoice = invoiceDetails.invoice
  const selectedLease = selectedInvoice ? leaseById.get(selectedInvoice.lease_id) : null
  const selectedTenant = selectedLease ? tenantById.get(selectedLease.tenant_id) : null
  const selectedUnit = selectedLease ? unitById.get(selectedLease.unit_id) : null
  const selectedProperty = selectedUnit ? propertyById.get(selectedUnit.property_id) : null

  if (selectedInvoiceId !== null) {
    return (
      <section className="management-page" aria-labelledby="invoice-detail-heading">
        <button className="back-button" type="button" onClick={() => { setSelectedInvoiceId(null); setIssueState({ busy: false, error: '' }) }}>
          <span aria-hidden="true">←</span> {invoiceChargeLabel(purpose)} invoices
        </button>
        {invoiceDetails.loading ? (
          <div className="overview-message" role="status" aria-live="polite"><span className="loading-dot" aria-hidden="true" /> Loading invoice details…</div>
        ) : invoiceDetails.error ? (
          <div className="overview-message overview-error" role="alert">
            <div><h4>Invoice details could not be loaded</h4><p>{invoiceDetails.error}</p></div>
            <button className="retry-button" type="button" onClick={() => setDetailRetry((count) => count + 1)}>Try again</button>
          </div>
        ) : selectedInvoice && (
          <>
            <div className="management-page-heading detail-heading invoice-detail-heading">
              <div>
                <p className="eyebrow">{invoiceChargeLabel(selectedInvoice.purpose)} invoice · {selectedInvoice.period_start} to {selectedInvoice.period_end}</p>
                <h2 id="invoice-detail-heading">{selectedTenant?.full_name || 'Tenant unavailable'}</h2>
                <p>{selectedProperty?.name || 'Property unavailable'}{selectedUnit ? ` · Unit ${selectedUnit.unit_number}` : ''}</p>
              </div>
              <span className={`status-pill invoice-lifecycle status-${selectedInvoice.status}`}>{invoiceChargeLabel(selectedInvoice.status)}</span>
            </div>
            <div className="invoice-meta-grid">
              <div><span>Billing period</span><strong>{selectedInvoice.period_start} – {selectedInvoice.period_end}</strong></div>
              <div><span>Purpose</span><strong>{invoiceChargeLabel(selectedInvoice.purpose)}</strong></div>
              <div><span>Due date</span><strong>{selectedInvoice.due_date}</strong></div>
              <div><span>Tenant</span><strong>{selectedTenant?.full_name || 'Unavailable'}</strong></div>
              <div><span>Property / unit</span><strong>{selectedProperty?.name || 'Unavailable'}{selectedUnit ? ` · ${selectedUnit.unit_number}` : ''}</strong></div>
            </div>
            <section className="invoice-charges-detail" aria-labelledby="invoice-charges-heading">
              <div className="property-section-heading"><h3 id="invoice-charges-heading">Charges</h3></div>
              <ul className="invoice-detail-charge-list">
                {selectedInvoice.charges.map((charge) => (
                  <li className="invoice-detail-charge" key={charge.id}>
                    <div className="invoice-detail-charge-heading">
                      <div><strong>{invoiceChargeLabel(charge.category)}</strong>{charge.description && <span>{charge.description}</span>}</div>
                      <strong>{formatKes(charge.amount)}</strong>
                    </div>
                    {charge.utility_breakdowns.length > 0 && (
                      <div className="utility-breakdown-list">
                        {charge.utility_breakdowns.map((breakdown) => (
                          <div key={breakdown.category}><span>{invoiceChargeLabel(breakdown.category)}</span><span>{formatKes(breakdown.amount)}</span></div>
                        ))}
                      </div>
                    )}
                    <div className="charge-financials">
                      <span>Paid {formatKes(charge.paid_amount)}</span>
                      <span>Outstanding {formatKes(charge.outstanding_balance)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
            <section className="invoice-balance-card" aria-label="Invoice totals and payment progress">
              <div><span>Invoice total</span><strong>{formatKes(selectedInvoice.total_amount)}</strong></div>
              <div><span>Paid</span><strong>{formatKes(selectedInvoice.paid_amount)}</strong></div>
              <div><span>Outstanding</span><strong>{formatKes(selectedInvoice.outstanding_balance)}</strong></div>
              <div className="invoice-payment-progress"><span>Payment progress</span><strong>{invoicePaymentProgress(selectedInvoice)}</strong></div>
            </section>
            {issueState.error && <div className="form-error lease-action-error" role="alert">{issueState.error}</div>}
            {selectedInvoice.status === 'draft' && (
              <div className="lease-actions">
                <button className="primary-button compact-button" type="button" disabled={issueState.busy} onClick={issueInvoice}>
                  {issueState.busy ? 'Issuing…' : 'Issue invoice'}
                </button>
              </div>
            )}
          </>
        )}
      </section>
    )
  }

  return (
    <section className="management-page" aria-labelledby="invoices-page-heading">
      <div className="management-page-heading">
        <div>
          <p className="eyebrow">{purpose === 'rent' ? 'Rent billing' : 'Utility billing'}</p>
          <h2 id="invoices-page-heading">{invoiceChargeLabel(purpose)} Invoices</h2>
          <p>{purpose === 'rent' ? 'Review rent charges, invoice lifecycle, and payment balances.' : purpose === 'utilities' ? 'Review combined water and garbage charges, breakdowns, and payment balances.' : 'Review other invoice charges, lifecycle, and payment balances.'}</p>
        </div>
      </div>
      {data.loading ? (
        <div className="overview-message" role="status" aria-live="polite"><span className="loading-dot" aria-hidden="true" /> Loading invoices and lease information…</div>
      ) : data.error ? (
        <div className="overview-message overview-error" role="alert">
          <div><h4>Invoice information could not be loaded</h4><p>{data.error}</p></div>
          <button className="retry-button" type="button" onClick={retry}>Try again</button>
        </div>
      ) : data.invoices.filter((invoice) => invoice.purpose === purpose).length === 0 ? (
        <div className="overview-empty compact-empty">
          <h4>No {invoiceChargeLabel(purpose)} invoices yet</h4>
          <p>{purpose === 'rent' ? 'Rent invoices created through Monthly Billing or manual invoice creation will appear here.' : purpose === 'utilities' ? 'Utilities invoices created through Monthly Billing or manual invoice creation will appear here.' : 'Other invoices created through manual invoice creation will appear here.'}</p>
        </div>
      ) : (
        <ul className="invoice-list">
          {data.invoices.filter((invoice) => invoice.purpose === purpose).map((invoice) => {
            const lease = leaseById.get(invoice.lease_id)
            const tenant = lease ? tenantById.get(lease.tenant_id) : null
            const unit = lease ? unitById.get(lease.unit_id) : null
            const property = unit ? propertyById.get(unit.property_id) : null
            return (
              <li key={invoice.id}>
                <button className="invoice-list-card" type="button" onClick={() => setSelectedInvoiceId(invoice.id)}>
                  <span className="invoice-list-main">
                    <strong>{tenant?.full_name || 'Tenant unavailable'}</strong>
                    <span>{property?.name || 'Property unavailable'}{unit ? ` · Unit ${unit.unit_number}` : ''}</span>
                    <small>{invoice.period_start} – {invoice.period_end} · Due {invoice.due_date}</small>
                  </span>
                  <span className="invoice-list-total"><strong>{formatKes(invoice.total_amount)}</strong><small>{invoiceChargeLabel(invoice.purpose)} · {invoiceChargeLabel(invoice.status)}</small></span>
                  <span className="invoice-list-balance"><span>Paid {formatKes(invoice.paid_amount)}</span><span>Outstanding {formatKes(invoice.outstanding_balance)}</span><small>{invoicePaymentProgress(invoice)}</small></span>
                  <span className={`status-pill invoice-lifecycle status-${invoice.status}`}>{invoiceChargeLabel(invoice.status)}</span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

function FinancialOverviewPage() {
  const [month, setMonth] = useState(currentBillingMonth)
  const [propertyId, setPropertyId] = useState('')
  const [reportState, setReportState] = useState({ loading: true, properties: [], report: null, error: '' })
  const [retryCount, setRetryCount] = useState(0)

  useEffect(() => {
    let isCurrent = true
    async function loadReport() {
      setReportState((current) => ({ ...current, loading: true, error: '' }))
      try {
        const params = new URLSearchParams({ month })
        if (propertyId) params.set('property_id', propertyId)
        const [propertyResult, report] = await Promise.all([
          apiRequest('/api/properties', { authenticated: true }),
          apiRequest(`/api/reports/financial?${params.toString()}`, { authenticated: true }),
        ])
        if (!Array.isArray(propertyResult?.properties) || !report?.billed_during_month) {
          throw new Error('Financial overview data could not be read. Please try again.')
        }
        if (isCurrent) setReportState({ loading: false, properties: propertyResult.properties, report, error: '' })
      } catch (error) {
        if (isCurrent) setReportState((current) => ({ ...current, loading: false, error: error.message || 'Unable to load financial data.' }))
      }
    }
    loadReport()
    return () => { isCurrent = false }
  }, [month, propertyId, retryCount])

  const report = reportState.report
  const billed = report?.billed_during_month
  const collections = report?.allocations_received_during_month
  const outstanding = report?.outstanding_current_issued_invoices
  const collectionRates = report?.collection_rates_percent

  function percentage(value) {
    return value === null || value === undefined ? '—' : `${value}%`
  }

  return (
    <section className="management-page financial-overview-page" aria-labelledby="financial-overview-heading">
      <div className="management-page-heading">
        <div>
          <p className="eyebrow">Portfolio reporting</p>
          <h2 id="financial-overview-heading">Financial Overview</h2>
          <p>Review billed charges, allocations, and current invoice balances for your portfolio.</p>
        </div>
      </div>

      <div className="financial-report-filters">
        <div className="field-group">
          <label htmlFor="financial-report-month">Reporting month</label>
          <input id="financial-report-month" type="month" value={month} disabled={reportState.loading} onChange={(event) => setMonth(event.target.value)} />
        </div>
        <div className="field-group">
          <label htmlFor="financial-report-property">Property</label>
          <select id="financial-report-property" value={propertyId} disabled={reportState.loading} onChange={(event) => setPropertyId(event.target.value)}>
            <option value="">All properties</option>
            {reportState.properties.map((property) => <option key={property.id} value={property.id}>{property.name}</option>)}
          </select>
        </div>
        {report && <p className="report-timezone">Reporting calendar: {report.timezone}</p>}
      </div>

      {reportState.loading ? (
        <div className="overview-message" role="status" aria-live="polite"><span className="loading-dot" aria-hidden="true" /> Loading financial overview…</div>
      ) : reportState.error ? (
        <div className="overview-message overview-error" role="alert">
          <div><h4>Financial overview could not be loaded</h4><p>{reportState.error}</p></div>
          <button className="retry-button" type="button" onClick={() => setRetryCount((count) => count + 1)}>Try again</button>
        </div>
      ) : (
        <>
          {reportState.properties.length === 0 && (
            <div className="report-empty-note">No properties are registered yet. Financial totals will appear here after invoices and allocations are recorded.</div>
          )}

          <section className="report-section" aria-labelledby="billed-heading">
            <div className="report-section-heading"><div><h3 id="billed-heading">Billed during {month}</h3><p>Charges on invoices issued during this month.</p></div></div>
            <div className="report-metric-grid report-purpose-grid">
              {[
                ['Rent', billed.rent],
                ['Utilities', billed.utilities],
                ['Other', billed.other],
                ['Total billed', billed.total],
              ].map(([label, amount]) => (
                <article className={`report-metric${label === 'Total billed' ? ' report-metric-emphasis' : ''}`} key={label}>
                  <span>{label}</span><strong>{formatKes(amount)}</strong>
                </article>
              ))}
            </div>
            <div className="report-utility-breakdown">
              <strong>Utilities detail</strong>
              <span>Water {formatKes(report.utility_breakdown_billed_during_month.water)}</span>
              <span>Garbage {formatKes(report.utility_breakdown_billed_during_month.garbage)}</span>
              <small>Water and garbage are included in the utilities amount above.</small>
            </div>
          </section>

          <section className="report-section" aria-labelledby="collections-heading">
            <div className="report-section-heading"><div><h3 id="collections-heading">Allocated during {month}</h3><p>Payment allocations created this month, including allocations to older invoices.</p></div></div>
            <div className="report-metric-grid">
              {[
                ['Rent allocations', collections.rent],
                ['Utilities allocations', collections.utilities],
                ['Other allocations', collections.other],
                ['Total allocated', collections.total],
              ].map(([label, amount]) => <article className="report-metric" key={label}><span>{label}</span><strong>{formatKes(amount)}</strong></article>)}
            </div>
          </section>

          <section className="report-section" aria-labelledby="outstanding-heading">
            <div className="report-section-heading"><div><h3 id="outstanding-heading">Current outstanding balances</h3><p>As of {new Date(report.outstanding_as_of).toLocaleString('en-KE', { timeZone: 'Africa/Nairobi' })} EAT · all issued invoices, including older months.</p></div></div>
            <div className="report-metric-grid">
              {[
                ['Rent outstanding', outstanding.rent],
                ['Utilities outstanding', outstanding.utilities],
                ['Other outstanding', outstanding.other],
                ['Total outstanding', outstanding.total],
              ].map(([label, amount]) => <article className="report-metric" key={label}><span>{label}</span><strong>{formatKes(amount)}</strong></article>)}
            </div>
          </section>

          <section className="report-section" aria-labelledby="collection-rate-heading">
            <div className="report-section-heading"><div><h3 id="collection-rate-heading">Collection rates</h3><p>Each rate uses billed amounts for the selected month as its denominator. A dash means there was no billed amount.</p></div></div>
            <div className="report-rate-explanation"><p><strong>Current collection on this month’s invoices:</strong> allocations currently applied to invoices issued this month ÷ this month’s billed amount.</p><p><strong>Allocated during this month:</strong> allocations created this month ÷ this month’s billed amount. This can exceed 100% when older arrears are collected.</p></div>
            <div className="report-table-wrap">
              <table className="report-rate-table">
                <thead><tr><th scope="col">Purpose</th><th scope="col">Current on this month’s invoices</th><th scope="col">Allocated during this month</th></tr></thead>
                <tbody>{['rent', 'utilities', 'other', 'total'].map((purpose) => (
                  <tr key={purpose}>
                    <th scope="row">{purpose === 'total' ? 'All purposes' : purpose[0].toUpperCase() + purpose.slice(1)}</th>
                    <td>{percentage(collectionRates[purpose].current_paid_on_invoices_issued_in_month.rate)}</td>
                    <td>{percentage(collectionRates[purpose].allocations_received_during_month.rate)}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </section>

          <section className="report-section" aria-labelledby="property-breakdown-heading">
            <div className="report-section-heading"><div><h3 id="property-breakdown-heading">By property</h3><p>Monthly activity and current outstanding balances for each property in the selection.</p></div></div>
            {report.property_breakdown.length === 0 ? (
              <div className="overview-empty compact-empty"><h4>No property breakdown to show</h4><p>Add properties and issue invoices to see financial activity by property.</p></div>
            ) : (
              <ul className="report-property-list">
                {report.property_breakdown.map((item) => (
                  <li className="report-property-card" key={item.property_id}>
                    <div className="report-property-heading"><h4>{item.property_name}</h4><span>{formatKes(item.billed_during_month.total)} billed</span></div>
                    <div className="report-property-metrics">
                      <span>Allocated this month <strong>{formatKes(item.allocations_received_during_month.total)}</strong></span>
                      <span>Current outstanding <strong>{formatKes(item.outstanding_current_issued_invoices.total)}</strong></span>
                      <span>Water / garbage <strong>{formatKes(item.utility_breakdown_billed_during_month.water)} / {formatKes(item.utility_breakdown_billed_during_month.garbage)}</strong></span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </section>
  )
}

function DashboardShell({ user }) {
  const { logout } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  const [page, setPage] = useState('Overview')
  const [dataVersion, setDataVersion] = useState(0)
  const [selectedInvoiceId, setSelectedInvoiceId] = useState(null)
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
    setSelectedInvoiceId(null)
    setMenuOpen(false)
    if (window.matchMedia('(max-width: 760px)').matches) {
      menuButtonRef.current?.focus()
    }
  }

  function openInvoice(invoiceId, purpose) {
    setPage(purpose === 'utilities' ? 'Utilities Invoices' : purpose === 'other' ? 'Other Invoices' : 'Rent Invoices')
    setSelectedInvoiceId(invoiceId)
    setMenuOpen(false)
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
          ) : page === 'Financial Overview' ? (
            <FinancialOverviewPage />
          ) : page === 'Properties' ? (
            <PropertiesPage onDataChanged={() => setDataVersion((version) => version + 1)} />
          ) : page === 'Tenants' ? (
            <TenantsPage />
          ) : page === 'Leases' ? (
            <LeasesPage />
          ) : page === 'Monthly Billing' ? (
            <MonthlyBillingPage onOpenInvoice={openInvoice} />
          ) : page === 'Rent Invoices' ? (
            <InvoicesPage purpose="rent" selectedInvoiceId={selectedInvoiceId} setSelectedInvoiceId={setSelectedInvoiceId} />
          ) : page === 'Utilities Invoices' ? (
            <InvoicesPage purpose="utilities" selectedInvoiceId={selectedInvoiceId} setSelectedInvoiceId={setSelectedInvoiceId} />
          ) : page === 'Other Invoices' ? (
            <InvoicesPage purpose="other" selectedInvoiceId={selectedInvoiceId} setSelectedInvoiceId={setSelectedInvoiceId} />
          ) : (
            <LeasesPage />
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
