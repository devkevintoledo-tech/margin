// FastAPI returns errors as { detail: ... }. For our HTTPExceptions `detail`
// is a string; for 422 validation errors it's an array of {msg, ...} objects.
// Normalize both into a single user-facing string.
export function errorMessage(error, fallback = 'Something went wrong. Please try again.') {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail[0]?.msg || 'Please check your input.'
  }
  // Librarian merge/split confirmations answer { detail: { message, consequences } }.
  if (detail && typeof detail.message === 'string') return detail.message
  return fallback
}
