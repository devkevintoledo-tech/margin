import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Link } from 'react-router-dom'
import DataTable from './DataTable'

const columns = [
  { key: 'score', label: 'Score', align: 'right', width: 6, sortable: true, render: (r) => r.score },
  {
    key: 'title',
    label: 'Thread',
    sortable: true,
    render: (r) => <Link to={`/books/1/threads/${r.id}`}>{r.title}</Link>,
  },
]

const rows = [
  { id: '1', score: '+42', title: 'Is Anarres actually a utopia?' },
  { id: '2', score: '-3', title: 'Overrated' },
]

function renderTable(props = {}) {
  return render(
    <MemoryRouter>
      <DataTable columns={columns} rows={rows} caption="Discussions" {...props} />
    </MemoryRouter>,
  )
}

describe('DataTable', () => {
  it('renders a row per record', () => {
    renderTable()
    expect(screen.getAllByRole('row')).toHaveLength(3) // header + 2
  })

  it('renders row links as real anchors', () => {
    renderTable()
    expect(screen.getByRole('link', { name: 'Overrated' })).toHaveAttribute(
      'href',
      '/books/1/threads/2',
    )
  })

  it('calls onSort with the column key when a sortable header is clicked', async () => {
    const onSort = vi.fn()
    renderTable({ onSort })
    await userEvent.click(screen.getByRole('button', { name: /sort by score/i }))
    expect(onSort).toHaveBeenCalledWith('score')
  })

  it('exposes the active sort column to assistive tech', () => {
    renderTable({ onSort: vi.fn(), sort: 'score', sortDirection: 'desc' })
    const header = screen.getByRole('columnheader', { name: /score/i })
    expect(header).toHaveAttribute('aria-sort', 'descending')
  })

  it('renders plain headers when no onSort handler is given', () => {
    renderTable()
    expect(screen.queryByRole('button', { name: /sort by/i })).not.toBeInTheDocument()
  })

  it('shows the empty message instead of a table when there are no rows', () => {
    renderTable({ rows: [], emptyMessage: 'No discussions yet.' })
    expect(screen.getByText('No discussions yet.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('gives the table an accessible caption', () => {
    renderTable()
    expect(screen.getByRole('table', { name: 'Discussions' })).toBeInTheDocument()
  })
})
