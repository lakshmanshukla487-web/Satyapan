import { useCallback, useEffect, useState } from 'react'
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(() => { setLoading(true); setError(null); fn().then(setData).catch((e: unknown) => setError(e instanceof Error ? e.message : 'Unknown error')).finally(() => setLoading(false)) }, deps)
  useEffect(run, [run])
  return { data, error, loading, reload: run }
}
