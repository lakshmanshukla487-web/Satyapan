import { useCallback, useEffect, useRef, useState } from 'react'

/** Loads data once and on reload(), without request storms or stale answers:
 *  - only one request runs at a time; reload() while one is running schedules exactly one more afterwards (coalesced),
 *  - an answer that arrives after the inputs changed (or after unmount) is ignored,
 *  - `loading` is only true until the first answer; later reloads keep showing the previous data and set `refreshing`,
 *  - a failed reload keeps the previous data (`error` is set so the page can show a small warning instead of going blank). */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const gen = useRef(0)
  const inFlight = useRef(false)
  const again = useRef(false)
  const fnRef = useRef(fn)
  fnRef.current = fn

  const exec = useCallback((g: number) => {
    inFlight.current = true
    setRefreshing(true)
    fnRef.current()
      .then((d) => { if (g === gen.current) { setData(d); setError(null) } })
      .catch((e: unknown) => { if (g === gen.current) setError(e instanceof Error ? e.message : 'Unknown error') })
      .finally(() => {
        if (g !== gen.current) return
        inFlight.current = false
        setLoading(false)
        setRefreshing(false)
        if (again.current) { again.current = false; exec(g) }
      })
  }, [])

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const reload = useCallback(() => { if (inFlight.current) { again.current = true; return } exec(gen.current) }, deps)

  useEffect(() => {
    const g = ++gen.current  // new inputs: forget whatever is still running for the old ones
    inFlight.current = false
    again.current = false
    setLoading(true)
    setData(null)
    setError(null)
    exec(g)
    return () => { gen.current++ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, error, loading, refreshing, reload, setData }
}
