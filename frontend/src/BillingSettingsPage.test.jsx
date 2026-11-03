import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import BillingSettingsPage from './BillingSettingsPage.jsx'
import { apiRequest } from './api/client.js'

vi.mock('./api/client.js', () => ({
  apiRequest: vi.fn(),
}))

const initialSettings = {
  rent_due_day: 5,
  utilities_due_day: 12,
}

describe('BillingSettingsPage', () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockResolvedValue(initialSettings)
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('retrieves settings through the authenticated API request', async () => {
    render(<BillingSettingsPage />)

    await screen.findByLabelText('Rent invoices due day')

    expect(apiRequest).toHaveBeenCalledWith(
      '/api/billing-settings',
      { authenticated: true },
    )
  })

  it('shows the due days returned by the API as the initial values', async () => {
    render(<BillingSettingsPage />)

    expect(await screen.findByLabelText('Rent invoices due day')).toHaveValue('5')
    expect(screen.getByLabelText('Utilities invoices due day')).toHaveValue('12')
  })

  it('keeps rent and utilities selections independent and submits both values', async () => {
    render(<BillingSettingsPage />)

    const rentDay = await screen.findByLabelText('Rent invoices due day')
    const utilitiesDay = screen.getByLabelText('Utilities invoices due day')
    fireEvent.change(rentDay, { target: { value: '8' } })
    fireEvent.change(utilitiesDay, { target: { value: '20' } })

    expect(rentDay).toHaveValue('8')
    expect(utilitiesDay).toHaveValue('20')

    vi.mocked(apiRequest).mockResolvedValueOnce({
      message: 'Saved.',
      rent_due_day: 8,
      utilities_due_day: 20,
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))

    expect(await screen.findByText('Saved.')).toBeInTheDocument()
    expect(apiRequest).toHaveBeenLastCalledWith('/api/billing-settings', {
      method: 'PUT',
      authenticated: true,
      body: {
        rent_due_day: 8,
        utilities_due_day: 20,
      },
    })
  })

  it('shows the successful save feedback from the API', async () => {
    render(<BillingSettingsPage />)

    await screen.findByLabelText('Rent invoices due day')
    vi.mocked(apiRequest).mockResolvedValueOnce({
      message: 'Billing preferences saved.',
      rent_due_day: 5,
      utilities_due_day: 12,
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Billing preferences saved.',
    )
  })

  it('displays a load error and retries the request', async () => {
    vi.mocked(apiRequest)
      .mockRejectedValueOnce(new Error('Service unavailable.'))
      .mockResolvedValueOnce(initialSettings)
    render(<BillingSettingsPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Service unavailable.',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByLabelText('Rent invoices due day')).toHaveValue('5')
    expect(apiRequest).toHaveBeenCalledTimes(2)
  })

  it('displays a save error without losing the selected values', async () => {
    render(<BillingSettingsPage />)

    const rentDay = await screen.findByLabelText('Rent invoices due day')
    fireEvent.change(rentDay, { target: { value: '9' } })
    vi.mocked(apiRequest).mockRejectedValueOnce(new Error('Save failed.'))
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Save failed.')
    expect(rentDay).toHaveValue('9')
  })

  it('rejects invalid settings returned while loading', async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      rent_due_day: 0,
      utilities_due_day: 12,
    })
    render(<BillingSettingsPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Billing settings could not be read.',
    )
    expect(screen.queryByLabelText('Rent invoices due day')).not.toBeInTheDocument()
  })

  it('reports an invalid save response and keeps the existing selection', async () => {
    render(<BillingSettingsPage />)

    const utilitiesDay = await screen.findByLabelText('Utilities invoices due day')
    fireEvent.change(utilitiesDay, { target: { value: '18' } })
    vi.mocked(apiRequest).mockResolvedValueOnce({
      rent_due_day: 5,
      utilities_due_day: 31,
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'updated values could not be read',
    )
    expect(utilitiesDay).toHaveValue('18')
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Save settings' })).toBeEnabled()
    })
  })
})
