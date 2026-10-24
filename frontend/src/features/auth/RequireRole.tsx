import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Loading } from '../../components/ui'
import type { Role } from '../../types'
import { useAuth } from './AuthContext'
import { homeFor } from './authService'

/** Route guard: signed out -> /login (and back afterwards); wrong role -> that role's own dashboard. */
export function RequireRole({ role }: { role: Role }) {
  const { user, ready } = useAuth()
  const loc = useLocation()
  if (!ready) return <Loading />
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  if (user.role !== role) return <Navigate to={homeFor(user.role)} replace />
  return <Outlet />
}
