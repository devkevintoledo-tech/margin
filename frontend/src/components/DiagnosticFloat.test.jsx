import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import DiagnosticFloat from './DiagnosticFloat'

describe('DiagnosticFloat', () => {
  it('renders its trigger', () => {
    render(
      <DiagnosticFloat severity="warn" message="edited 2h ago">
        edited
      </DiagnosticFloat>,
    )
    expect(screen.getByText('edited')).toBeInTheDocument()
  })

  it('wires the trigger to the tooltip with aria-describedby', () => {
    render(
      <DiagnosticFloat severity="info" message="posted 3 March 2026">
        2h
      </DiagnosticFloat>,
    )
    const tooltip = screen.getByRole('tooltip')
    const trigger = screen.getByText('2h')
    expect(trigger).toHaveAttribute('aria-describedby', tooltip.id)
  })

  it('names the severity in text, not colour alone', () => {
    render(
      <DiagnosticFloat severity="error" message="failed to load">
        !
      </DiagnosticFloat>,
    )
    expect(screen.getByText(/error/i)).toBeInTheDocument()
  })

  it('renders the dim source line when given one', () => {
    render(
      <DiagnosticFloat severity="warn" message="edited 2h ago" source="thread/42">
        edited
      </DiagnosticFloat>,
    )
    expect(screen.getByText('thread/42')).toBeInTheDocument()
  })

  it('makes the trigger keyboard-focusable', () => {
    render(
      <DiagnosticFloat severity="hint" message="hint text">
        ?
      </DiagnosticFloat>,
    )
    expect(screen.getByText('?')).toHaveAttribute('tabindex', '0')
  })
})
