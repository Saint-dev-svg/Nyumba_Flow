import { useEffect, useRef, useState } from 'react'
import { apiRequest } from './api/client.js'

function isValidBillingDueDay(value) {
  return Number.isInteger(value) && value >= 1 && value <= 28
}

export default function BillingSettingsPage() {
  const [settings, setSettings] = useState({
    loading: true,
    rentDueDay: 1,
    utilitiesDueDay: 1,
    error: '',
  })
  const [retryCount, setRetryCount] = useState(0)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')
  const savingRef = useRef(false)

  useEffect(() => {
    let isCurrent = true

    async function fetchSettings() {
      setSettings((current) => ({ ...current, loading: true, error: '' }))
      try {
        const result = await apiRequest('/api/billing-settings', { authenticated: true })
        if (!isValidBillingDueDay(result?.rent_due_day) || !isValidBillingDueDay(result?.utilities_due_day)) {
          throw new Error('Billing settings could not be read. Please try again.')
        }
        if (isCurrent) {
          setSettings({
            loading: false,
            rentDueDay: result.rent_due_day,
            utilitiesDueDay: result.utilities_due_day,
            error: '',
          })
        }
      } catch (error) {
        if (isCurrent) {
          setSettings((current) => ({
            ...current,
            loading: false,
            error: error.message || 'Unable to load billing settings.',
          }))
        }
      }
    }

    fetchSettings()
    return () => { isCurrent = false }
  }, [retryCount])

  async function handleSubmit(event) {
    event.preventDefault()
    if (savingRef.current) return

    const rentDueDay = Number(settings.rentDueDay)
    const utilitiesDueDay = Number(settings.utilitiesDueDay)
    if (!isValidBillingDueDay(rentDueDay) || !isValidBillingDueDay(utilitiesDueDay)) {
      setSaveError('Choose a due day from 1 to 28 for both rent and utilities.')
      setSuccessMessage('')
      return
    }

    savingRef.current = true
    setSaving(true)
    setSaveError('')
    setSuccessMessage('')
    try {
      const result = await apiRequest('/api/billing-settings', {
        method: 'PUT',
        authenticated: true,
        body: {
          rent_due_day: rentDueDay,
          utilities_due_day: utilitiesDueDay,
        },
      })
      if (!isValidBillingDueDay(result?.rent_due_day) || !isValidBillingDueDay(result?.utilities_due_day)) {
        throw new Error('Billing settings were saved, but the updated values could not be read. Please reload the page.')
      }
      setSettings({
        loading: false,
        rentDueDay: result.rent_due_day,
        utilitiesDueDay: result.utilities_due_day,
        error: '',
      })
      setSuccessMessage(result.message || 'Billing settings updated successfully.')
    } catch (error) {
      setSaveError(error.message || 'Unable to save billing settings.')
    } finally {
      savingRef.current = false
      setSaving(false)
    }
  }

  return (
    <section className="management-page" aria-labelledby="billing-settings-heading">
      <div className="management-page-heading">
        <div>
          <p className="eyebrow">Landlord preferences</p>
          <h2 id="billing-settings-heading">Billing Settings</h2>
          <p>Choose when rent and utility invoices are due each month.</p>
        </div>
      </div>

      <div className="billing-settings-notice" role="note">
        Changes to due days apply to future invoices only. Existing invoices retain their original due dates.
      </div>

      {settings.loading ? (
        <div className="overview-message" role="status" aria-live="polite">
          <span className="loading-dot" aria-hidden="true" />
          Loading billing settings…
        </div>
      ) : settings.error ? (
        <div className="overview-message overview-error" role="alert">
          <div>
            <h4>Billing settings could not be loaded</h4>
            <p>{settings.error}</p>
          </div>
          <button className="retry-button" type="button" onClick={() => setRetryCount((count) => count + 1)}>
            Try again
          </button>
        </div>
      ) : (
        <form className="management-form" onSubmit={handleSubmit} noValidate aria-labelledby="billing-settings-form-heading">
          <div className="management-form-heading">
            <h3 id="billing-settings-form-heading">Invoice due days</h3>
          </div>
          <div className="management-fields">
            <div className="field-group">
              <label htmlFor="rent-due-day">Rent invoices due day</label>
              <select
                id="rent-due-day"
                required
                value={settings.rentDueDay}
                disabled={saving}
                onChange={(event) => {
                  setSettings((current) => ({ ...current, rentDueDay: Number(event.target.value) }))
                  setSaveError('')
                  setSuccessMessage('')
                }}
              >
                {Array.from({ length: 28 }, (_, index) => index + 1).map((day) => (
                  <option key={day} value={day}>{day}</option>
                ))}
              </select>
            </div>
            <div className="field-group">
              <label htmlFor="utilities-due-day">Utilities invoices due day</label>
              <select
                id="utilities-due-day"
                required
                value={settings.utilitiesDueDay}
                disabled={saving}
                onChange={(event) => {
                  setSettings((current) => ({ ...current, utilitiesDueDay: Number(event.target.value) }))
                  setSaveError('')
                  setSuccessMessage('')
                }}
              >
                {Array.from({ length: 28 }, (_, index) => index + 1).map((day) => (
                  <option key={day} value={day}>{day}</option>
                ))}
              </select>
            </div>
          </div>
          {saveError && <div className="form-error" role="alert">{saveError}</div>}
          {successMessage && <div className="billing-settings-success" role="status" aria-live="polite">{successMessage}</div>}
          <div className="management-form-actions">
            <button className="primary-button compact-button" type="submit" disabled={saving}>
              {saving ? 'Saving…' : 'Save settings'}
            </button>
          </div>
        </form>
      )}
    </section>
  )
}
