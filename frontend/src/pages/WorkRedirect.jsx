import { useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useWork } from '../api/works'

/**
 * The work page is retired: a book's page is its series. Old links — search
 * history, shared URLs, threads started before series existed — land here and
 * are replaced with their series URL, so the back button skips this hop.
 */
function WorkRedirect() {
  const { id, threadId } = useParams()
  const navigate = useNavigate()
  const { data: work, isError } = useWork(id)

  useEffect(() => {
    if (!work?.series) return
    const target = threadId
      ? `/series/${work.series.slug}/threads/${threadId}`
      : `/series/${work.series.slug}?book=${work.id}`
    navigate(target, { replace: true })
  }, [work, threadId, navigate])

  if (isError) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <p className="alert-danger">Could not find this book.</p>
      </main>
    )
  }
  return (
    <main className="max-w-shell mx-auto px-4 py-8">
      <div className="animate-pulse h-10 bg-panel w-1/2" />
    </main>
  )
}

export default WorkRedirect
