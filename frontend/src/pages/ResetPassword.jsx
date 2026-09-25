import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useResetPassword } from '../api/auth'
import { errorMessage } from '../api/errors'
import AuthLayout from '../components/AuthLayout'
import { useStatusBar } from '../store/status'

function ResetPassword() {
  useStatusBar({ mode: 'AUTH', path: '~/reset-password', facts: [] })

  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [formError, setFormError] = useState('')
  const navigate = useNavigate()
  const { mutate: resetPassword, isPending, isSuccess, error } = useResetPassword()

  // Redirect to sign in shortly after a successful reset. The timer is cleared
  // on unmount so navigate() never fires on an unmounted component.
  useEffect(() => {
    if (!isSuccess) return
    const id = setTimeout(() => navigate('/login'), 1500)
    return () => clearTimeout(id)
  }, [isSuccess, navigate])

  const handleSubmit = (e) => {
    e.preventDefault()
    if (password.length < 8) {
      setFormError('Password must be at least 8 characters.')
      return
    }
    if (password !== confirm) {
      setFormError('Passwords do not match.')
      return
    }
    setFormError('')
    resetPassword({ token, new_password: password })
  }

  return (
    <AuthLayout title="Choose a new password" subtitle="Enter and confirm your new password.">
      {isSuccess ? (
        <div className="alert-muted">Your password has been reset. Redirecting to sign in...</div>
      ) : (
        <>
          {(formError || error || !token) && (
            <div className="alert-danger mb-6">
              {formError ||
                (!token
                  ? 'This reset link is invalid or has expired.'
                  : errorMessage(error, 'Could not reset password. Please try again.'))}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="label">New password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
                className="input py-3"
              />
            </div>
            <div>
              <label className="label">Confirm password</label>
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
                className="input py-3"
              />
            </div>
            <button type="submit" disabled={isPending} className="btn-primary-lg w-full mt-2">
              {isPending ? 'Resetting...' : 'Reset password'}
            </button>
          </form>
        </>
      )}
    </AuthLayout>
  )
}

export default ResetPassword
