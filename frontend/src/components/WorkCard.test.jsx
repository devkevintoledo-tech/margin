import { fireEvent, render, screen } from '@testing-library/react'
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

  const inSeries = { ...work, series: { slug: 'red-rising', name: 'Red Rising', kind: 'series' } }
  const alone = { ...work, series: { slug: 'the-hobbit-a1b2c3', name: 'The Hobbit', kind: 'singleton' } }

  it('opens the series page at this book', () => {
    renderCard(inSeries)
    expect(screen.getByRole('link')).toHaveAttribute('href', '/series/red-rising?book=w1')
  })

  it('opens a singleton at its own series page', () => {
    renderCard(alone)
    expect(screen.getByRole('link')).toHaveAttribute('href', '/series/the-hobbit-a1b2c3?book=w1')
  })

  it('falls back to the legacy work URL when no series is known', () => {
    renderCard(work)
    expect(screen.getByRole('link')).toHaveAttribute('href', '/works/w1')
  })

  it('names the series a book belongs to', () => {
    renderCard(inSeries)
    expect(screen.getByText('series')).toBeInTheDocument()
    expect(screen.getByText('Red Rising', { selector: '.text-path' })).toBeInTheDocument()
  })

  it('shows no series tag for a book that stands alone', () => {
    renderCard(alone)
    expect(screen.queryByText('series')).not.toBeInTheDocument()
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

  it('falls back to the title when the cover fails to load', () => {
    renderCard({ ...work, cover_url: 'https://example.test/dead.jpg' })
    fireEvent.error(screen.getByRole('img', { name: 'Red Rising' }))
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getAllByText('Red Rising').length).toBeGreaterThan(0)
  })
})
