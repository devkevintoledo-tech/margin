import React, { Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import Navbar from './components/Navbar'
import StatusBar from './components/StatusBar'
import { useMe } from './api/auth'

const Home = React.lazy(() => import('./pages/Home'))
const Book = React.lazy(() => import('./pages/Book'))
const Thread = React.lazy(() => import('./pages/Thread'))
const Genre = React.lazy(() => import('./pages/Genre'))
const Search = React.lazy(() => import('./pages/Search'))
const Profile = React.lazy(() => import('./pages/Profile'))
const Login = React.lazy(() => import('./pages/Login'))
const Register = React.lazy(() => import('./pages/Register'))
const ForgotPassword = React.lazy(() => import('./pages/ForgotPassword'))
const ResetPassword = React.lazy(() => import('./pages/ResetPassword'))
const NotFound = React.lazy(() => import('./pages/NotFound'))

function App() {
  // Validate any persisted token on load. useMe() is enabled only when a token
  // exists; a 401 is handled by the client interceptor, which clears the store.
  useMe()

  return (
    <div className="min-h-screen bg-bg text-ink">
      <Navbar />
      <Suspense fallback={<div className="flex items-center justify-center h-64 text-ink-dim">Loading...</div>}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/books/:id" element={<Book />} />
          <Route path="/books/:id/threads/:threadId" element={<Thread />} />
          <Route path="/genres/:slug" element={<Genre />} />
          {/* Genre threads have always been linked as /genres/:slug/threads/:threadId;
              without this route those links fell through to NotFound. */}
          <Route path="/genres/:slug/threads/:threadId" element={<Thread />} />
          <Route path="/search" element={<Search />} />
          <Route path="/profile/:username" element={<Profile />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
      <StatusBar />
    </div>
  )
}

export default App
