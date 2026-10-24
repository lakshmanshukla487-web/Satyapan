import { Link } from 'react-router-dom'
import { btnPrimary } from '../components/ui'
export default function NotFoundPage() { return <div className="space-y-4 py-16 text-center"><h1 className="text-2xl font-semibold text-white">Page not found</h1><p className="text-slate-400">The address does not match any Satyapan page.</p><Link to="/" className={btnPrimary}>Go home</Link></div> }
