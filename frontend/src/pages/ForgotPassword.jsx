import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useForgotPassword } from '../api/auth'
import AuthLayout from '../components/AuthLayout'

const CONFIRMATION = 'If an account with that email exists, a reset link has been sent.'

function ForgotPassword() {
  const [email, setEmail] = useState('')
  const { mutate: forgotPassword, isPending, isSuccess } = useForgotPassword()

  const handleSubmit = (e) => {
    e.preventDefault()
    forgotPassword({ email })
  }

  return (
    <AuthLayout
      title="Reset password"
      subtitle="We'll email you a reset link."
      footer={
        <>
          Remembered it?{' '}
          <Link to="/login" className="text-accent hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      {isSuccess ? (
        <div className="alert-muted">{CONFIRMATION}</div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="label">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="input py-3"
            />
          </div>
          <button type="submit" disabled={isPending} className="btn-primary-lg w-full mt-2">
            {isPending ? 'Sending...' : 'Send reset link'}
          </button>
        </form>
      )}
    </AuthLayout>
  )
}

export default ForgotPassword
