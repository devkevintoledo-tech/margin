/**
 * An `ls -l` listing: aligned columns, an underlined header row, and the header
 * itself as the sort control.
 *
 * Below `sm` the table collapses to stacked blocks. A horizontally scrolling
 * table on a phone is the one place this aesthetic genuinely fails, so it is
 * abandoned deliberately rather than scrolled.
 *
 * Cells render real `<a href>` links — never onClick row handlers — so
 * middle-click, keyboard navigation and screen readers all work.
 */
function DataTable({
  columns,
  rows,
  sort,
  sortDirection = 'desc',
  onSort,
  caption,
  emptyMessage = 'Nothing here yet.',
}) {
  if (!rows || rows.length === 0) {
    return <p className="text-ink-dim text-sm py-4">{emptyMessage}</p>
  }

  const alignClass = (align) => (align === 'right' ? 'text-right' : 'text-left')

  return (
    <table className="w-full max-w-table text-sm border-collapse block sm:table">
      <caption className="sr-only">{caption}</caption>

      <thead className="hidden sm:table-header-group">
        <tr className="border-b border-line">
          {columns.map((col) => {
            const active = sort === col.key
            return (
              <th
                key={col.key}
                scope="col"
                aria-sort={
                  !col.sortable || !onSort
                    ? undefined
                    : active
                      ? sortDirection === 'asc'
                        ? 'ascending'
                        : 'descending'
                      : 'none'
                }
                style={col.width ? { width: `${col.width}ch` } : undefined}
                className={`py-2 px-2 font-medium text-xs uppercase tracking-eyebrow text-ink-dim ${alignClass(col.align)}`}
              >
                {col.sortable && onSort ? (
                  <button
                    type="button"
                    onClick={() => onSort(col.key)}
                    aria-label={`Sort by ${col.label}`}
                    className="inline-flex items-center gap-1 hover:text-ink transition-colors duration-fast"
                  >
                    {col.label}
                    <span aria-hidden="true" className="text-ink-faint">
                      {active ? (sortDirection === 'asc' ? '▴' : '▾') : ''}
                    </span>
                  </button>
                ) : (
                  col.label
                )}
              </th>
            )
          })}
        </tr>
      </thead>

      <tbody className="block sm:table-row-group">
        {rows.map((row) => (
          <tr
            key={row.id}
            className="block sm:table-row border-b border-line/60 hover:bg-highlight transition-colors duration-fast"
          >
            {columns.map((col) => (
              <td
                key={col.key}
                className={`block sm:table-cell py-2 px-2 align-top ${alignClass(col.align)}`}
              >
                {col.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default DataTable
