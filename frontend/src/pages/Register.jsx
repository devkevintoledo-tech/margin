import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useRegister } from '../api/auth'
import { errorMessage } from '../api/errors'
import AuthLayout from '../components/AuthLayout'

function Register() {
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [formError, setFormError] = useState('')
  const navigate = useNavigate()
  const { mutate: register, isPending, error } = useRegister()

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
    register({ email, username, password }, { onSuccess: () => navigate('/') })
  }

  return (
    <AuthLayout
      title="Create account"
      subtitle="Join the conversation."
      footer={
        <>
          Already have an account?{' '}
          <Link to="/login" className="text-accent hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      {(formError || error) && (
        <div className="alert-danger mb-6">
          {formError || errorMessage(error, 'Registration failed. Please try again.')}
        </div>
      )}

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
        <div>
          <label className="label">Username</label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            className="input py-3"
          />
        </div>
        <div>
          <label className="label">Password</label>
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
          {isPending ? 'Creating account...' : 'Create account'}
        </button>
      </form>
    </AuthLayout>
  )
}

export default Register
