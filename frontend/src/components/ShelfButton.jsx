import { useState, useRef, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useAddToShelf, useUpdateShelf, useRemoveFromShelf } from '../api/works'
import useAuthStore from '../store/auth'

const SHELF_LABELS = {
  want_to_read: 'want to read',
  reading: 'reading',
  read: 'read',
}

const SHELF_TONE = {
  want_to_read: 'text-ink-dim',
  reading: 'text-warning',
  read: 'text-ok',
}

function ShelfButton({ workId, currentStatus }) {
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
      removeMutation.mutate({ id: workId })
    } else if (currentStatus) {
      updateMutation.mutate({ id: workId, status })
    } else {
      addMutation.mutate({ id: workId, status })
    }
  }

  const label = currentStatus ? SHELF_LABELS[currentStatus] : 'add to library'

  return (
    <div className="relative inline-block self-start" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={isPending}
        aria-expanded={open}
        className="btn-secondary text-xs"
      >
        {isPending ? 'Saving...' : label}
        <span aria-hidden="true" className="text-ink-faint">{open ? '▴' : '▾'}</span>
      </button>

      {open && (
        <div className="float absolute top-full left-0 mt-1 z-20 min-w-full p-0">
          {Object.entries(SHELF_LABELS).map(([status, lbl]) => (
            <button
              key={status}
              onClick={() => handleSelect(status)}
              className={`block w-full text-left px-3 py-1.5 text-xs hover:bg-highlight transition-colors duration-fast ${
                currentStatus === status ? SHELF_TONE[status] : 'text-ink-dim'
              }`}
            >
              {lbl}
            </button>
          ))}
          {currentStatus && (
            <button
              onClick={() => handleSelect(null)}
              className="block w-full text-left px-3 py-1.5 text-xs text-danger hover:bg-highlight transition-colors duration-fast border-t border-line"
            >
              remove
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export default ShelfButton
