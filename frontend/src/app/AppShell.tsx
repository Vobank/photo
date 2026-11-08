import { Aperture, Cube, GearSix, SquaresFour } from '@phosphor-icons/react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useShallow } from 'zustand/react/shallow'

import { useSystem } from '../api/queries'
import { formatBytes } from '../lib/format'
import { type View, navigate } from '../lib/router'
import { activeJobs, useLive } from '../state/live'
import styles from './AppShell.module.css'

const NAV: { view: View; icon: typeof Aperture; key: string }[] = [
  { view: 'studio', icon: Aperture, key: 'nav.studio' },
  { view: 'gallery', icon: SquaresFour, key: 'nav.gallery' },
  { view: 'models', icon: Cube, key: 'nav.models' },
  { view: 'settings', icon: GearSix, key: 'nav.settings' },
]

export function AppShell({ view, children }: { view: View; children: ReactNode }) {
  const { t } = useTranslation()
  return (
    <div className={styles.shell}>
      <nav className={styles.rail} aria-label={t('nav.label')}>
        <div className={styles.mark} aria-hidden>
          <span />
        </div>
        {NAV.map(({ view: v, icon: Icon, key }) => (
          <a
            key={v}
            href={v === 'studio' ? '/' : `/${v}`}
            className={styles.navItem}
            aria-current={view === v ? 'page' : undefined}
            onClick={(e) => {
              if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
              e.preventDefault()
              navigate({ view: v })
            }}
          >
            <Icon size={20} weight={view === v ? 'fill' : 'regular'} />
            <span>{t(key)}</span>
          </a>
        ))}
      </nav>
      <main className={styles.main}>{children}</main>
      <StatusBar />
    </div>
  )
}

function StatusBar() {
  const { t, i18n } = useTranslation()
  const { data: system } = useSystem()
  const connected = useLive((s) => s.connected)
  const engine = useLive((s) => s.engine) ?? system?.engine
  const queue = useLive((s) => activeJobs(s.jobs).length)
  const installs = useLive(useShallow((s) => Object.values(s.installs).filter((i) => !i.finished)))

  const state = !connected ? 'offline' : (engine?.state ?? 'starting')
  return (
    <footer className={styles.status}>
      <span className={styles.state} data-state={state} title={engine?.error ?? undefined}>
        <i aria-hidden />
        {t(`engine.${state}`)}
      </span>
      {system?.gpu && (
        <span className={styles.dim}>
          {system.gpu.name.replace(/^NVIDIA (GeForce )?/, '')} · {system.gpu.vram_gb} GB
        </span>
      )}
      {installs.map((i) => (
        <span key={i.model_id} className={styles.dim}>
          {t('status.downloading', {
            done: formatBytes(i.done, i18n.language),
            total: formatBytes(i.total, i18n.language),
          })}
        </span>
      ))}
      <span className={styles.spacer} />
      {queue > 0 && <span>{t('status.queue', { count: queue })}</span>}
      {system && <span className={`${styles.dim} num`}>v{system.version}</span>}
    </footer>
  )
}
