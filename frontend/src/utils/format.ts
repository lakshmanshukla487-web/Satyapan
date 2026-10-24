export const fmtTime = (iso: string | null) => (iso ? new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : 'Not available')
export const signalCount = (s: { signals: { status: string }[] }) => s.signals.filter((x) => x.status === 'available' || x.status === 'flagged').length
