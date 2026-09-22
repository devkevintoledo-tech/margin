import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useCreatePost } from '../api/threads'
import { errorMessage } from '../api/errors'
import useAuthStore from '../store/auth'

function PostComposer({ threadId, parentId = null, onSuccess, placeholder = 'Write a reply...' }) {
  const [content, setContent] = useState('')
  const user = useAuthStore((s) => s.user)
  const mutation = useCreatePost()

  if (!user) {
    return (
      <p className="text-ink-dim text-sm py-2">
        <Link to="/login" className="text-accent-ink hover:underline">Log in</Link> to post.
      </p>
    )
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!content.trim()) return
    mutation.mutate(
      { thread_id: threadId, parent_id: parentId, content: content.trim() },
      {
        onSuccess: () => {
          setContent('')
          onSuccess?.()
        },
      }
    )
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2">
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder={placeholder}
        rows={3}
        className="input resize-none"
      />
      <div className="flex justify-end">
        <button type="submit" disabled={mutation.isPending || !content.trim()} className="btn-primary">
          {mutation.isPending ? 'Posting...' : 'Post'}
        </button>
      </div>
      {mutation.isError && (
        <p className="text-danger text-xs">{errorMessage(mutation.error, 'Failed to post.')}</p>
      )}
    </form>
  )
}

export default PostComposer
