import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

type ToastState = { message: string; error?: boolean } | null

const ToastCtx = createContext<{
  toast: ToastState
  show: (message: string, error?: boolean) => void
  clear: () => void
} | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastState>(null)

  const show = useCallback((message: string, error = false) => {
    setToast({ message, error })
    window.setTimeout(() => setToast(null), 4200)
  }, [])

  const clear = useCallback(() => setToast(null), [])

  const value = useMemo(() => ({ toast, show, clear }), [toast, show, clear])

  return (
    <ToastCtx.Provider value={value}>
      {children}
      {toast && <div className={`toast${toast.error ? ' error' : ''}`}>{toast.message}</div>}
    </ToastCtx.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastCtx)
  if (!ctx) throw new Error('useToast requires ToastProvider')
  return ctx
}
