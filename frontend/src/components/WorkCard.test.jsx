import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import WorkCard from './WorkCard'

function renderCard(work) {
  return render(
    <MemoryRouter>
      <WorkCard work={work} />
    </MemoryRouter>,
  )
}

describe('WorkCard', () => {
  const work = {
    id: 'w1',
    title: 'Red Rising',
    author: 'Pierce Brown',
    cover_url: 'https://x/cover.jpg',
    edition_count: 26,
  }

  it('links to the work, not to an edition', () => {
    renderCard(work)
    expect(screen.getByRole('link')).toHaveAttribute('href', '/works/w1')
  })

  it('shows the cover with the title as its accessible name', () => {
    renderCard(work)
    expect(screen.getByRole('img', { name: 'Red Rising' })).toBeInTheDocument()
  })

  it('reports the edition count, so collapsing results reads as information', () => {
    renderCard(work)
    expect(screen.getByText('26 editions')).toBeInTheDocument()
  })

  it('says nothing about editions when there is only one', () => {
    renderCard({ ...work, edition_count: 1 })
    expect(screen.queryByText(/editions/)).not.toBeInTheDocument()
  })

  it('falls back to the title when there is no cover', () => {
    renderCard({ ...work, cover_url: null })
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getAllByText('Red Rising').length).toBeGreaterThan(0)
  })
})
