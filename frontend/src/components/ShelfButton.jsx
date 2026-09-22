import { useState, useRef, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useAddToShelf, useUpdateShelf, useRemoveFromShelf } from '../api/books'
import useAuthStore from '../store/auth'

const SHELF_LABELS = {
  want_to_read: 'Want to Read',
  reading: 'Reading',
  read: 'Read',
}

function ShelfButton({ bookId, currentStatus }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const user = useAuthStore((s) => s.user)
  const addMutation = useAddToShelf()
  const updateMutation = useUpdateShelf()
  const removeMutation = useRemoveFromShelf()

  const isPending = addMutation.isPending || updateMutation.isPending || removeMutation.isPending

  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  if (!user) {
    return (
      <Link to="/login" className="btn-secondary self-start">
        Log in to add to shelf
      </Link>
    )
  }

  const handleSelect = (status) => {
    setOpen(false)
    if (status === null) {
      removeMutation.mutate({ id: bookId })
    } else if (currentStatus) {
      updateMutation.mutate({ id: bookId, status })
    } else {
      addMutation.mutate({ id: bookId, status })
    }
  }

  const label = currentStatus ? SHELF_LABELS[currentStatus] : 'Add to Library'

  return (
    <div className="relative inline-block self-start" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={isPending}
        aria-expanded={open}
        className={currentStatus ? 'btn-primary uppercase tracking-wider text-xs' : 'btn-secondary uppercase tracking-wider text-xs'}
      >
        {isPending ? 'Saving...' : label}
        <span className="text-[0.6rem]">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-0.5 z-20 bg-raised border border-line-strong min-w-full">
          {Object.entries(SHELF_LABELS).map(([status, lbl]) => (
            <button
              key={status}
              onClick={() => handleSelect(status)}
              className={`block w-full text-left px-4 py-2 text-sm hover:bg-line transition-colors duration-fast ${
                currentStatus === status ? 'text-accent-ink' : 'text-ink-dim'
              }`}
            >
              {lbl}
            </button>
          ))}
          {currentStatus && (
            <button
              onClick={() => handleSelect(null)}
              className="block w-full text-left px-4 py-2 text-sm text-danger hover:bg-line transition-colors duration-fast border-t border-line"
            >
              Remove from Library
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export default ShelfButton
