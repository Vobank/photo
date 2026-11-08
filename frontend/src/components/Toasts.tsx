import styles from './Toasts.module.css'
import { useToasts } from './toast'

export function Toasts() {
  const { toasts, dismiss } = useToasts()
  return (
    <div className={styles.region} role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`${styles.toast} ${t.tone === 'error' ? styles.error : ''}`}>
          <span>{t.message}</span>
          {t.action && (
            <button
              type="button"
              className={styles.action}
              onClick={() => {
                t.action?.run()
                dismiss(t.id)
              }}
            >
              {t.action.label}
            </button>
          )}
        </div>
      ))}
    </div>
  )
}
