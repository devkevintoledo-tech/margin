import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import PathHeader from './PathHeader'

function renderPath(segments) {
  return render(
    <MemoryRouter>
      <PathHeader segments={segments} />
    </MemoryRouter>,
  )
}

describe('PathHeader', () => {
  it('renders a home root link', () => {
    renderPath([{ label: 'Books', to: '/books' }])
    expect(screen.getByRole('link', { name: '~' })).toHaveAttribute('href', '/')
  })

  it('slugifies segment labels', () => {
    renderPath([{ label: 'The Dispossessed', to: '/works/1' }])
    expect(screen.getByRole('link', { name: 'the-dispossessed' })).toHaveAttribute(
      'href',
      '/works/1',
    )
  })

  it('renders the final segment as text when it has no destination', () => {
    renderPath([
      { label: 'Books', to: '/books' },
      { label: 'Thread 42' },
    ])
    expect(screen.queryByRole('link', { name: 'thread-42' })).not.toBeInTheDocument()
    expect(screen.getByText('thread-42')).toBeInTheDocument()
  })

  it('labels itself as a breadcrumb for assistive tech', () => {
    renderPath([{ label: 'Books', to: '/books' }])
    expect(screen.getByRole('navigation', { name: /breadcrumb/i })).toBeInTheDocument()
  })

  it('renders nothing when there are no segments', () => {
    const { container } = renderPath([])
    expect(container).toBeEmptyDOMElement()
  })
})
