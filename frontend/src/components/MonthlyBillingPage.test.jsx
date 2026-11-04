import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import MonthlyBillingPage from './MonthlyBillingPage.jsx'
import { apiRequest } from '../api/client.js'

vi.mock('../api/client.js', () => ({
  apiRequest: vi.fn(),
}))

const property = { id: 42, name: 'Acacia Court' }
const unit = {
  id: 7,
  property_id: property.id,
  unit_number: 'A1',
  is_active: true,
}
const billingMonth = (() => {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
})()
const reading = {
  id: 15,
  unit_id: unit.id,
  previous_reading: '120.500',
  current_reading: '128.750',
}
const createdRentInvoice = {
  id: 81,
  lease_id: 17,
  unit_id: unit.id,
  purpose: 'rent',
  total_amount: '15000.00',
}

const expectedInitialRequests = [
  ['/api/invoices', { authenticated: true }],
  ['/api/leases', { authenticated: true }],
  ['/api/tenants', { authenticated: true }],
  ['/api/properties', { authenticated: true }],
  [`/api/properties/${property.id}/units`, { authenticated: true }],
  [`/api/properties/${property.id}/utility-settings`, { authenticated: true }],
  [`/api/properties/${property.id}/water-readings?billing_month=${billingMonth}`, { authenticated: true }],
]

function generationResponse({ created = [], existing = [], needsReadings = [] } = {}) {
  const [year, month] = billingMonth.split('-').map(Number)
  const periodEndDay = new Date(year, month, 0).getDate()
  return {
    message: 'Monthly draft generation completed.',
    billing_month: billingMonth,
    period_start: `${billingMonth}-01`,
    period_end: `${billingMonth}-${String(periodEndDay).padStart(2, '0')}`,
    rent_due_date: `${billingMonth}-05`,
    utilities_due_date: `${billingMonth}-12`,
    created_invoices: created,
    already_existing: existing,
    needs_readings: needsReadings,
    created_count: created.length,
    already_existing_count: existing.length,
    needs_reading_count: needsReadings.length,
  }
}

const mixedGenerationResponse = generationResponse({
  created: [createdRentInvoice],
  existing: [{ id: 82, lease_id: 18, unit_id: 8, purpose: 'utilities' }],
  needsReadings: [{
    lease_id: 19,
    tenant_id: 23,
    tenant_name: 'Sam Tenant',
    property_id: property.id,
    property_name: property.name,
    unit_id: unit.id,
    unit_number: unit.unit_number,
    reason: 'missing',
  }],
})

function configureSuccessfulApi({ generatedResult, generationError } = {}) {
  vi.mocked(apiRequest).mockImplementation(async (path, options = {}) => {
    if (path === '/api/invoices') return { invoices: [] }
    if (path === '/api/leases') return { leases: [] }
    if (path === '/api/tenants') return { tenants: [] }
    if (path === '/api/properties') return { properties: [property] }
    if (path === `/api/properties/${property.id}/units`) return { units: [unit] }
    if (path === `/api/properties/${property.id}/utility-settings`) {
      return { settings: { water_rate: '12.50', garbage_fee: '250.00' } }
    }
    if (path === `/api/properties/${property.id}/water-readings?billing_month=${billingMonth}`) {
      return { readings: [reading] }
    }
    if (path === '/api/invoices/generate-monthly' && options.method === 'POST') {
      if (generationError) throw generationError
      return generatedResult || generationResponse()
    }
    throw new Error(`Unexpected API request: ${path}`)
  })
}

function TestInvoiceForm({ leases, tenants, properties, units, invoices }) {
  return (
    <div>
      Manual invoice form
      <span>{[leases, tenants, properties, units, invoices].map((items) => items.length).join(',')}</span>
    </div>
  )
}

function renderPage(onOpenInvoice = vi.fn()) {
  return {
    onOpenInvoice,
    ...render(
      <MonthlyBillingPage
        onOpenInvoice={onOpenInvoice}
        InvoiceFormComponent={TestInvoiceForm}
      />,
    ),
  }
}

async function expectWorkspaceRefresh() {
  await waitFor(() => {
    for (const [path] of expectedInitialRequests.slice(0, 5)) {
      expect(vi.mocked(apiRequest).mock.calls.filter(([calledPath]) => calledPath === path)).toHaveLength(2)
    }
  })
}

describe('MonthlyBillingPage', () => {
  beforeEach(() => {
    configureSuccessfulApi()
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('loads the monthly billing workspace and selected-property utility data', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Monthly Billing' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Meter readings and draft generation' })).toBeInTheDocument()
    expect(screen.getByLabelText('Property rates')).toHaveValue(String(property.id))
    await waitFor(() => {
      expect(screen.getByLabelText('Previous reading')).toHaveValue(reading.previous_reading)
      expect(screen.getByLabelText('Current reading')).toHaveValue(reading.current_reading)
      expect(screen.getByLabelText('Water per unit (KES)')).toHaveValue('12.50')
      expect(screen.getByLabelText('Garbage per unit/month (KES)')).toHaveValue('250.00')
    })
    expect(screen.getByText(/Unit A1/)).toBeInTheDocument()

    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledTimes(expectedInitialRequests.length)
    })
    for (const [path, options] of expectedInitialRequests) {
      expect(apiRequest).toHaveBeenCalledWith(path, options)
    }
    expect(vi.mocked(apiRequest).mock.calls.every(([, options]) => options?.authenticated === true)).toBe(true)
  })

  it('reports invoices created on the first successful generation', async () => {
    const result = generationResponse({
      created: [
        createdRentInvoice,
        { id: 83, lease_id: 17, unit_id: unit.id, purpose: 'utilities', total_amount: '1200.00' },
      ],
    })
    configureSuccessfulApi({ generatedResult: result })
    renderPage()

    await screen.findByLabelText('Current reading')
    fireEvent.click(screen.getByRole('button', { name: 'Generate draft invoices' }))

    expect(await screen.findByRole('status')).toHaveTextContent('2 invoices created.')
    expect(screen.getByRole('button', { name: /Review rent draft/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Review utilities draft/ })).toBeInTheDocument()
  })

  it('explains that all invoices already exist and no duplicates were created', async () => {
    const result = generationResponse({
      existing: [
        { id: 82, lease_id: 17, unit_id: unit.id, purpose: 'rent' },
        { id: 83, lease_id: 17, unit_id: unit.id, purpose: 'utilities' },
      ],
    })
    configureSuccessfulApi({ generatedResult: result })
    renderPage()

    await screen.findByLabelText('Current reading')
    fireEvent.click(screen.getByRole('button', { name: 'Generate draft invoices' }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      'All invoices for this billing month already exist. No duplicate invoices were created.',
    )
    expect(screen.queryByRole('button', { name: /Review .* invoice/ })).not.toBeInTheDocument()
    expect(screen.queryByText('Already existing')).not.toBeInTheDocument()
  })

  it('reports mixed generation results, refreshes the workspace and opens a draft for review', async () => {
    configureSuccessfulApi({ generatedResult: mixedGenerationResponse })
    const { onOpenInvoice } = renderPage()

    await screen.findByLabelText('Current reading')
    fireEvent.click(screen.getByRole('button', { name: 'Generate draft invoices' }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      '1 invoice created; 1 invoice already existed; 1 unit need attention before utility invoices can be generated.',
    )
    expect(screen.queryByRole('button', { name: /Review .* invoice/ })).not.toBeInTheDocument()
    expect(apiRequest).toHaveBeenCalledWith('/api/invoices/generate-monthly', {
      method: 'POST',
      authenticated: true,
      body: { billing_month: billingMonth },
    })

    await expectWorkspaceRefresh()
    expect(vi.mocked(apiRequest).mock.calls.filter(([path]) => (
      path === expectedInitialRequests[5][0] || path === expectedInitialRequests[6][0]
    ))).toHaveLength(2)
    expect(vi.mocked(apiRequest).mock.calls.every(([, options]) => options?.authenticated === true)).toBe(true)

    fireEvent.click(await screen.findByRole('button', { name: /Review rent draft/ }))
    expect(onOpenInvoice).toHaveBeenCalledWith(createdRentInvoice.id, 'rent')
  })

  it('reports the number of units requiring readings and explains their reasons', async () => {
    const result = generationResponse({
      needsReadings: [
        {
          lease_id: 19,
          tenant_id: 23,
          tenant_name: 'Sam Tenant',
          property_id: property.id,
          property_name: property.name,
          unit_id: 7,
          unit_number: 'A1',
          reason: 'missing',
        },
        {
          lease_id: 20,
          tenant_id: 24,
          tenant_name: 'Alex Tenant',
          property_id: property.id,
          property_name: property.name,
          unit_id: 8,
          unit_number: 'A2',
          reason: 'invalid',
        },
      ],
    })
    configureSuccessfulApi({ generatedResult: result })
    renderPage()

    await screen.findByLabelText('Current reading')
    fireEvent.click(screen.getByRole('button', { name: 'Generate draft invoices' }))

    const summary = await screen.findByRole('status')
    expect(summary).toHaveTextContent('No invoices were created.')
    expect(summary).toHaveTextContent('2 units need attention before utility invoices can be generated.')
    expect(summary).toHaveTextContent('Unit A1: enter readings for this month')
    expect(summary).toHaveTextContent('Unit A2: correct the saved meter readings')
  })

  it('reports when no invoices are eligible for generation', async () => {
    configureSuccessfulApi({ generatedResult: generationResponse() })
    renderPage()

    await screen.findByLabelText('Current reading')
    fireEvent.click(screen.getByRole('button', { name: 'Generate draft invoices' }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      'No eligible invoices were found for this billing month. No invoices were created.',
    )
  })

  it('preserves the generation error feedback when the API request fails', async () => {
    configureSuccessfulApi({ generationError: new Error('Invoice service unavailable.') })
    renderPage()

    await screen.findByLabelText('Current reading')
    fireEvent.click(screen.getByRole('button', { name: 'Generate draft invoices' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Invoice service unavailable.')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(apiRequest).toHaveBeenCalledWith('/api/invoices/generate-monthly', {
      method: 'POST',
      authenticated: true,
      body: { billing_month: billingMonth },
    })
  })
})
