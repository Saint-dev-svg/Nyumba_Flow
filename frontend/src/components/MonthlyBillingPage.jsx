import { useEffect, useState } from 'react'
import { apiRequest } from '../api/client.js'

function currentBillingMonth() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

function moneyToCents(value) {
  const text = String(value).trim()
  if (!/^\d+(?:\.\d{1,2})?$/.test(text)) return null
  const [whole, fraction = ''] = text.split('.')
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))
  return cents <= 999999999999n ? cents : null
}

function readingToThousandths(value) {
  const text = String(value).trim()
  if (!/^\d+(?:\.\d{1,3})?$/.test(text)) return null
  const [whole, fraction = ''] = text.split('.')
  return BigInt(whole) * 1000n + BigInt(fraction.padEnd(3, '0'))
}

function formatKes(amount) {
  const [wholePart = '0', fractionalPart = ''] = String(amount).split('.')
  const groupedWhole = wholePart.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `KES ${groupedWhole}.${fractionalPart.padEnd(2, '0').slice(0, 2)}`
}

function MeterReadingAndBillingPanel({
  properties,
  units,
  onGenerated,
  onReviewInvoice,
}) {
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
  const unitsNeedingAttention = generationResult
    ? new Set(generationResult.needs_readings.map((item) => item.unit_id)).size
    : 0

  function generationFeedback() {
    if (
      generationResult.created_count === 0
      && generationResult.already_existing_count === 0
      && generationResult.needs_reading_count === 0
    ) {
      return 'No eligible invoices were found for this billing month. No invoices were created.'
    }
    if (
      generationResult.created_count === 0
      && generationResult.already_existing_count > 0
      && generationResult.needs_reading_count === 0
    ) {
      return 'All invoices for this billing month already exist. No duplicate invoices were created.'
    }

    const outcomes = []
    if (generationResult.created_count > 0) {
      outcomes.push(`${generationResult.created_count} invoice${generationResult.created_count === 1 ? '' : 's'} created`)
    }
    if (generationResult.already_existing_count > 0) {
      outcomes.push(`${generationResult.already_existing_count} invoice${generationResult.already_existing_count === 1 ? '' : 's'} already existed`)
    }
    if (unitsNeedingAttention > 0) {
      outcomes.push(`${unitsNeedingAttention} unit${unitsNeedingAttention === 1 ? '' : 's'} need attention before utility invoices can be generated`)
    }
    if (generationResult.created_count === 0) {
      return `No invoices were created. ${outcomes.join('; ')}.`
    }
    return `${outcomes.join('; ')}.`
  }

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
          <div><h4>Monthly billing results for {generationResult.billing_month}</h4><p>{generationFeedback()}</p></div>
          {generationResult.created_invoices.length > 0 && <div className="generation-summary-group"><strong>Created drafts</strong><ul>{generationResult.created_invoices.map((invoice) => <li key={invoice.id}><button className="text-button" type="button" onClick={() => onReviewInvoice(invoice.id, invoice.purpose)}>Review {invoice.purpose} draft · {formatKes(invoice.total_amount)}</button></li>)}</ul></div>}
          {generationResult.needs_readings.length > 0 && <div className="generation-summary-group generation-needs-readings"><strong>Units needing attention ({unitsNeedingAttention})</strong><ul>{generationResult.needs_readings.map((item) => <li key={`${item.unit_id}-${item.reason}`}>{item.property_name} · Unit {item.unit_number}: {item.reason === 'missing' ? 'enter readings for this month' : item.reason === 'invalid' ? 'correct the saved meter readings' : 'calculated utility amount exceeds the invoice limit'}</li>)}</ul></div>}
        </div>
      )}
    </section>
  )
}

export function useInvoiceWorkspaceData() {
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

export default function MonthlyBillingPage({
  onOpenInvoice,
  InvoiceFormComponent,
}) {
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

      {data.loading && data.properties.length === 0 ? (
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
            <InvoiceFormComponent
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
