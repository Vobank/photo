import { Check, CheckCircle, Circle, FolderSimple, HardDrives, Warning, WarningCircle, XCircle } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { type ReactNode, useEffect, useState } from 'react'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'

import { ApiError, api } from '../../api/client'
import type { Disk, FieldError, InstallConfig, SetupPlan, SetupRun, SetupStep } from '../../api/types'
import { Button } from '../../components/Button'
import fieldStyles from '../../components/Field.module.css'
import { LANGUAGES, setLanguage } from '../../i18n'
import { formatBytes } from '../../lib/format'
import { useLive } from '../../state/live'
import styles from './Setup.module.css'

type Stage = 'language' | 'storage' | 'models' | 'install'
const STAGES: Stage[] = ['language', 'storage', 'models', 'install']
type PathField = 'models_dir' | 'engine_env_dir' | 'data_dir'
const PATH_FIELDS: PathField[] = ['models_dir', 'engine_env_dir', 'data_dir']
const SAFETY_MARGIN = 2_000_000_000

const sepOf = (p: string) => (p.includes('\\') ? '\\' : '/')

/** Longest disk root that prefixes ``path`` (case-insensitive on Windows). */
function diskFor(path: string, disks: Disk[]): Disk | undefined {
  const win = path.includes('\\') || /^[a-z]:/i.test(path)
  const norm = (s: string) => (win ? s.toLowerCase() : s)
  return disks
    .filter((d) => norm(path).startsWith(norm(d.root)))
    .sort((a, b) => b.root.length - a.root.length)[0]
}

/** Move ``path`` to ``disk``, keeping its folder structure below the old root. */
function rebase(path: string, from: Disk | undefined, to: Disk): string {
  const sep = sepOf(to.root.includes('\\') ? '\\' : path)
  const rest = from ? path.slice(from.root.length) : path.replace(/^([a-z]:)?[\\/]*/i, '')
  const root = to.root.endsWith(sep) ? to.root : to.root + sep
  return root + rest.replace(/^[\\/]+/, '')
}

export default function SetupWizard() {
  const { t } = useTranslation()
  const plan = useQuery({ queryKey: ['setup-plan'], queryFn: api.setup.plan, staleTime: Infinity })
  if (plan.isError) {
    return (
      <Frame stage="language">
        <div className={styles.notice} data-tone="error">
          {t('errors.network')}
        </div>
      </Frame>
    )
  }
  if (!plan.data) return <Frame stage="language">{null}</Frame>
  return <Wizard data={plan.data} />
}

/** Saved choices when re-running (repair), otherwise defaults with English first. */
function initialConfig(plan: SetupPlan): InstallConfig {
  return {
    language: plan.configured ? plan.defaults.language : 'en',
    models_dir: plan.defaults.models_dir,
    data_dir: plan.defaults.data_dir,
    engine_env_dir: plan.defaults.engine_env_dir,
    models: plan.models.filter((m) => m.recommended || m.installed).map((m) => m.id),
  }
}

function Wizard({ data }: { data: SetupPlan }) {
  const { t, i18n } = useTranslation()
  const liveRun = useLive((s) => s.setupRun)
  const [stage, setStage] = useState<Stage>(() => (data.run.status === 'idle' ? 'language' : 'install'))
  const [cfg, setCfg] = useState<InstallConfig>(() => initialConfig(data))
  const [errors, setErrors] = useState<FieldError[]>([])
  const [busy, setBusy] = useState(false)

  // The wizard speaks the language being chosen.
  useEffect(() => {
    if (cfg.language !== i18n.language) void setLanguage(cfg.language)
  }, [cfg.language, i18n.language])

  const run = liveRun ?? data.run

  const blockers = systemBlockers(data)
  const idx = STAGES.indexOf(stage)
  const installing = run?.status === 'running' || run?.status === 'done'

  const next = async () => {
    if (stage === 'storage' || stage === 'models') {
      setBusy(true)
      try {
        const res = await api.setup.validate(cfg)
        setErrors(res.errors)
        const relevant = res.errors.filter((e) => (stage === 'models' ? true : e.field !== 'models'))
        if (relevant.length) return
      } catch {
        setErrors([{ field: '', code: 'network', detail: '' }])
        return
      } finally {
        setBusy(false)
      }
    }
    setStage(STAGES[idx + 1])
  }

  return (
    <Frame stage={stage} onJump={installing ? undefined : (s) => STAGES.indexOf(s) < idx && setStage(s)}>
      {stage === 'language' && <LanguageStage plan={data} cfg={cfg} setCfg={setCfg} blockers={blockers} />}
      {stage === 'storage' && <StorageStage plan={data} cfg={cfg} setCfg={setCfg} errors={errors} />}
      {stage === 'models' && <ModelsStage plan={data} cfg={cfg} setCfg={setCfg} errors={errors} />}
      {stage === 'install' && <InstallStage plan={data} cfg={cfg} run={run} onBack={() => setStage('storage')} />}

      {stage !== 'install' && (
        <footer className={styles.footer}>
          {idx > 0 ? (
            <Button variant="ghost" onClick={() => setStage(STAGES[idx - 1])}>
              {t('setup.back')}
            </Button>
          ) : (
            <span />
          )}
          <Button
            variant="primary"
            size="lg"
            disabled={busy || blockers.some((b) => b.fatal) || (stage === 'models' && cfg.models.length === 0 && !data.models.some((m) => m.installed))}
            onClick={() => void next()}
          >
            {t('setup.continue')}
          </Button>
        </footer>
      )}
    </Frame>
  )
}

function Frame({ stage, onJump, children }: { stage: Stage; onJump?: (s: Stage) => void; children: ReactNode }) {
  const { t } = useTranslation()
  const current = STAGES.indexOf(stage)
  return (
    <div className={styles.wizard}>
      <aside className={styles.side}>
        <div className={styles.brand}>
          <span className={styles.mark} aria-hidden />
          Photo
        </div>
        <ol className={styles.stages}>
          {STAGES.map((s, i) => (
            <li key={s} aria-current={s === stage ? 'step' : undefined} data-done={i < current}>
              <button type="button" disabled={!onJump || i >= current} onClick={() => onJump?.(s)}>
                <span className={styles.stageNum}>{i < current ? <Check size={12} weight="bold" /> : i + 1}</span>
                {t(`setup.stages.${s}`)}
              </button>
            </li>
          ))}
        </ol>
      </aside>
      <main className={styles.content}>
        <div className={styles.inner}>{children}</div>
      </main>
    </div>
  )
}

// ---- step 1: language and system check ------------------------------------------

interface Blocker {
  fatal: boolean
  text: string
}

/** Problems that make installing pointless until the user fixes them. */
function systemBlockers(plan: SetupPlan): Blocker[] {
  const gpu = plan.gpu
  if (!gpu) return [{ fatal: true, text: 'no_gpu' }]
  const out: Blocker[] = []
  if (!gpu.driver_ok) out.push({ fatal: true, text: 'driver_old' })
  if (!gpu.supported) out.push({ fatal: false, text: 'gpu_unsupported' })
  return out
}

function LanguageStage({
  plan,
  cfg,
  setCfg,
}: {
  plan: SetupPlan
  cfg: InstallConfig
  setCfg: (c: InstallConfig) => void
  blockers: Blocker[]
}) {
  const { t } = useTranslation()
  const gpu = plan.gpu
  return (
    <>
      <h1 className={styles.title}>{t('setup.language.title')}</h1>
      <p className={styles.lead}>{t('setup.language.lead')}</p>
      <div className={styles.languages} role="radiogroup" aria-label={t('setup.language.title')}>
        {LANGUAGES.filter((l) => plan.languages.includes(l.id)).map((l) => (
          <button
            key={l.id}
            type="button"
            role="radio"
            lang={l.id}
            dir={'dir' in l ? l.dir : 'ltr'}
            aria-checked={cfg.language === l.id}
            className={styles.language}
            onClick={() => setCfg({ ...cfg, language: l.id })}
          >
            {l.label}
          </button>
        ))}
      </div>

      <h2 className={styles.subtitle}>{t('setup.system.title')}</h2>
      <ul className={styles.checks}>
        {gpu ? (
          <>
            <CheckRow ok={gpu.supported} warn={!gpu.supported}>
              {t('setup.system.gpu', { name: gpu.name, vram: gpu.vram_gb })}
              {!gpu.supported && <small>{t('setup.system.gpuUnsupported')}</small>}
            </CheckRow>
            <CheckRow ok={gpu.driver_ok}>
              {t('setup.system.driver', { version: gpu.driver })}
              {!gpu.driver_ok && <small>{t('setup.system.driverOld', { min: plan.min_driver })}</small>}
            </CheckRow>
          </>
        ) : (
          <CheckRow ok={false}>
            {t('setup.system.noGpu')}
            <small>{t('setup.system.noGpuHelp')}</small>
          </CheckRow>
        )}
      </ul>
    </>
  )
}

function CheckRow({ ok, warn, children }: { ok: boolean; warn?: boolean; children: ReactNode }) {
  const Icon = ok ? CheckCircle : warn ? WarningCircle : XCircle
  return (
    <li className={styles.check} data-state={ok ? 'ok' : warn ? 'warn' : 'error'}>
      <Icon size={18} weight="fill" aria-hidden />
      <div>{children}</div>
    </li>
  )
}

// ---- step 2: storage ------------------------------------------------------------

function StorageStage({
  plan,
  cfg,
  setCfg,
  errors,
}: {
  plan: SetupPlan
  cfg: InstallConfig
  setCfg: (c: InstallConfig) => void
  errors: FieldError[]
}) {
  const { t, i18n } = useTranslation()
  const lng = i18n.language
  const usable = plan.disks.filter((d) => d.kind !== 'network')
  const modelBytes = plan.models.filter((m) => cfg.models.includes(m.id) && !m.installed).reduce((a, m) => a + m.bytes, 0)
  const needs: Record<PathField, number> = {
    models_dir: modelBytes,
    engine_env_dir: plan.engine_env_bytes,
    data_dir: plan.data_hint_bytes,
  }

  // Per-disk totals, so two locations on one drive are judged together.
  const totals = new Map<string, { disk: Disk; need: number }>()
  for (const f of PATH_FIELDS) {
    const d = diskFor(cfg[f], plan.disks)
    if (!d) continue
    const entry = totals.get(d.root) ?? { disk: d, need: 0 }
    entry.need += f === 'data_dir' ? 0 : needs[f]
    totals.set(d.root, entry)
  }
  const perDisk = [...totals.values()]

  return (
    <>
      <h1 className={styles.title}>{t('setup.storage.title')}</h1>
      <p className={styles.lead}>{t('setup.storage.lead')}</p>

      {PATH_FIELDS.map((f) => {
        const disk = diskFor(cfg[f], plan.disks)
        const fieldErrors = errors.filter((e) => e.field === f)
        return (
          <section key={f} className={styles.location}>
            <div className={styles.locationHead}>
              <div>
                <h3>{t(`setup.storage.${f}.title`)}</h3>
                <p>{t(`setup.storage.${f}.body`)}</p>
              </div>
              <span className={styles.need}>
                {needs[f] > 0
                  ? f === 'data_dir'
                    ? t('setup.storage.recommended', { size: formatBytes(needs[f], lng) })
                    : t('setup.storage.needs', { size: formatBytes(needs[f], lng) })
                  : t('setup.storage.alreadyThere')}
              </span>
            </div>
            <div className={styles.locationRow}>
              <select
                aria-label={t('setup.storage.drive')}
                className={fieldStyles.select}
                value={disk?.root ?? ''}
                onChange={(e) => {
                  const to = usable.find((d) => d.root === e.target.value)
                  if (to) setCfg({ ...cfg, [f]: rebase(cfg[f], disk, to) })
                }}
              >
                {!disk && <option value="">—</option>}
                {usable.map((d) => (
                  <option key={d.root} value={d.root}>
                    {driveLabel(d, t)} · {t('setup.storage.free', { size: formatBytes(d.free, lng) })}
                  </option>
                ))}
              </select>
              <input
                aria-label={t(`setup.storage.${f}.title`)}
                className={`${fieldStyles.input} num`}
                value={cfg[f]}
                spellCheck={false}
                dir="ltr"
                onChange={(e) => setCfg({ ...cfg, [f]: e.target.value })}
              />
            </div>
            {fieldErrors.map((e) => (
              <p key={e.code} className={styles.fieldError} role="alert">
                <Warning size={14} weight="fill" aria-hidden /> {fieldErrorText(t, e, lng)}
              </p>
            ))}
          </section>
        )
      })}

      <div className={styles.diskSummary}>
        {perDisk.map(({ disk, need }) => {
          const enough = disk.free >= need + SAFETY_MARGIN
          const used = disk.total - disk.free
          return (
            <div key={disk.root} className={styles.diskLine} data-ok={enough}>
              <HardDrives size={18} aria-hidden />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className={styles.diskName}>
                  <span>{driveLabel(disk, t)}</span>
                  <span>
                    {need > 0
                      ? t('setup.storage.diskNeed', { need: formatBytes(need, lng), free: formatBytes(disk.free, lng) })
                      : t('setup.storage.free', { size: formatBytes(disk.free, lng) })}
                  </span>
                </div>
                <div className={styles.diskBar} aria-hidden>
                  <span style={{ width: `${(used / disk.total) * 100}%` }} />
                  <span data-new style={{ width: `${(Math.min(need, disk.free) / disk.total) * 100}%` }} />
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </>
  )
}

function driveLabel(d: Disk, t: TFunction): string {
  const name = d.label ? `${d.root.replace(/\\$/, '')} ${d.label}` : d.root.replace(/\\$/, '')
  return d.kind === 'removable' ? `${name} (${t('setup.storage.removable')})` : name
}

function fieldErrorText(t: TFunction, e: FieldError, lng: string): string {
  if (e.code === 'not_enough_space') {
    const [need, free] = e.detail.split(':').map(Number)
    return t('setup.errors.not_enough_space', { need: formatBytes(need, lng), free: formatBytes(free, lng) })
  }
  return t(`setup.errors.${e.code}`, { defaultValue: e.detail || e.code })
}

// ---- step 3: models -------------------------------------------------------------

function ModelsStage({
  plan,
  cfg,
  setCfg,
  errors,
}: {
  plan: SetupPlan
  cfg: InstallConfig
  setCfg: (c: InstallConfig) => void
  errors: FieldError[]
}) {
  const { t, i18n } = useTranslation()
  const toggle = (id: string) =>
    setCfg({ ...cfg, models: cfg.models.includes(id) ? cfg.models.filter((m) => m !== id) : [...cfg.models, id] })
  const total = plan.models.filter((m) => cfg.models.includes(m.id) && !m.installed).reduce((a, m) => a + m.bytes, 0)
  return (
    <>
      <h1 className={styles.title}>{t('setup.models.title')}</h1>
      <p className={styles.lead}>{t('setup.models.lead')}</p>
      <div className={styles.modelList}>
        {plan.models.map((m) => (
          <label key={m.id} className={styles.model} data-checked={cfg.models.includes(m.id) || m.installed}>
            <input
              type="checkbox"
              checked={cfg.models.includes(m.id) || m.installed}
              disabled={m.installed}
              onChange={() => toggle(m.id)}
            />
            <div className={styles.modelBody}>
              <div className={styles.modelHead}>
                <strong>{m.name}</strong>
                {m.recommended && <span className={styles.tag}>{t('setup.models.recommended')}</span>}
                <span className={`${styles.size} num`}>
                  {m.installed ? t('models.installed') : formatBytes(m.bytes, i18n.language)}
                </span>
              </div>
              <p>{t(`modelInfo.${m.id}`, { defaultValue: '' })}</p>
              <small>
                {m.vendor} · {m.variant} ·{' '}
                <a href={m.license_url} target="_blank" rel="noreferrer noopener">
                  {m.license}
                </a>{' '}
                · {m.commercial_use ? t('models.commercialOk') : t('models.nonCommercial')}
              </small>
            </div>
          </label>
        ))}
      </div>
      {total > 0 && <p className={styles.total}>{t('setup.models.total', { size: formatBytes(total, i18n.language) })}</p>}
      {errors
        .filter((e) => e.field === 'models' || e.code === 'not_enough_space')
        .slice(0, 1)
        .map((e) => (
          <p key={e.code} className={styles.fieldError} role="alert">
            <Warning size={14} weight="fill" aria-hidden /> {fieldErrorText(t, e, i18n.language)}
          </p>
        ))}
    </>
  )
}

// ---- step 4: install ------------------------------------------------------------

function InstallStage({
  plan,
  cfg,
  run,
  onBack,
}: {
  plan: SetupPlan
  cfg: InstallConfig
  run: SetupRun | null
  onBack: () => void
}) {
  const { t, i18n } = useTranslation()
  const [startError, setStartError] = useState<string | null>(null)
  const [opening, setOpening] = useState(false)
  const status = run?.status ?? 'idle'

  const start = async () => {
    setStartError(null)
    try {
      await api.setup.start(cfg)
    } catch (e) {
      setStartError(e instanceof ApiError ? (e.fields[0]?.code ? t(`setup.errors.${e.fields[0].code}`) : e.message) : t('errors.network'))
    }
  }

  const open = async () => {
    setOpening(true)
    await api.setup.finish().catch(() => undefined)
    // The installer starts Photo on this same address; wait for it, then switch over.
    for (let i = 0; i < 240; i++) {
      await new Promise((r) => setTimeout(r, 1000))
      try {
        const s = await api.system()
        if (s.mode === 'app') {
          location.replace('/')
          return
        }
      } catch {
        /* not up yet */
      }
    }
    setOpening(false)
  }

  if (status === 'idle') {
    return (
      <>
        <h1 className={styles.title}>{t('setup.install.title')}</h1>
        <p className={styles.lead}>{t('setup.install.lead')}</p>
        <dl className={styles.summary}>
          <dt>{t('setup.stages.language')}</dt>
          <dd>{LANGUAGES.find((l) => l.id === cfg.language)?.label}</dd>
          {PATH_FIELDS.map((f) => (
            <FragmentRow key={f} label={t(`setup.storage.${f}.title`)} value={cfg[f]} />
          ))}
          <dt>{t('setup.stages.models')}</dt>
          <dd>{plan.models.filter((m) => cfg.models.includes(m.id)).map((m) => m.name).join(', ') || '—'}</dd>
        </dl>
        {startError && (
          <p className={styles.fieldError} role="alert">
            <Warning size={14} weight="fill" aria-hidden /> {startError}
          </p>
        )}
        <footer className={styles.footer}>
          <Button variant="ghost" onClick={onBack}>
            {t('setup.back')}
          </Button>
          <Button variant="primary" size="lg" onClick={() => void start()}>
            {t('setup.install.start')}
          </Button>
        </footer>
      </>
    )
  }

  return (
    <>
      <h1 className={styles.title}>
        {status === 'done' ? t('setup.install.doneTitle') : status === 'failed' ? t('setup.install.failedTitle') : t('setup.install.runningTitle')}
      </h1>
      <p className={styles.lead}>
        {status === 'done' ? t('setup.install.doneLead') : status === 'failed' ? '' : t('setup.install.runningLead')}
      </p>
      <ol className={styles.progress}>
        {run?.steps.map((s) => <StepRow key={s.id} step={s} lng={i18n.language} />)}
      </ol>

      {status === 'failed' && run?.error && (
        <div className={styles.notice} data-tone="error" role="alert">
          <p>{t(`setup.errors.${run.error.code}`, { defaultValue: t('setup.errors.setup_failed') })}</p>
          {run.error.detail && (
            <details>
              <summary>{t('setup.install.details')}</summary>
              <pre>{run.error.detail}</pre>
            </details>
          )}
        </div>
      )}

      <footer className={styles.footer}>
        {status === 'failed' ? (
          <>
            <Button variant="ghost" onClick={onBack}>
              {t('setup.install.change')}
            </Button>
            <Button variant="primary" size="lg" onClick={() => void start()}>
              {t('actions.retry')}
            </Button>
          </>
        ) : status === 'done' ? (
          <>
            <span />
            <Button variant="primary" size="lg" disabled={opening} onClick={() => void open()}>
              {opening ? t('setup.install.opening') : t('setup.install.open')}
            </Button>
          </>
        ) : (
          <>
            <span className={styles.keepOpen}>{t('setup.install.keepOpen')}</span>
            <Button variant="ghost" onClick={() => void api.setup.cancel()}>
              {t('actions.cancel')}
            </Button>
          </>
        )}
      </footer>
    </>
  )
}

function FragmentRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd className={`${styles.path} num`} dir="ltr">
        <FolderSimple size={14} aria-hidden />
        {value}
      </dd>
    </>
  )
}

function StepRow({ step, lng }: { step: SetupStep; lng: string }) {
  const { t } = useTranslation()
  const Icon =
    step.status === 'done' || step.status === 'skipped' ? CheckCircle : step.status === 'failed' ? XCircle : Circle
  const frac = step.total ? step.done / step.total : 0
  return (
    <li className={styles.step} data-status={step.status}>
      <Icon size={18} weight={step.status === 'pending' ? 'regular' : 'fill'} aria-hidden />
      <div className={styles.stepBody}>
        <div className={styles.stepHead}>
          <span>{t(`setup.steps.${step.id}`)}</span>
          <span className={step.status === 'running' && step.total ? 'num' : undefined}>
            {step.status === 'skipped'
              ? t('setup.install.upToDate')
              : step.status === 'running' && step.total
                ? `${formatBytes(step.done, lng)} / ${formatBytes(step.total, lng)}`
                : ''}
          </span>
        </div>
        {step.status === 'running' && (
          <div className={styles.bar} data-indeterminate={!step.total}>
            <span style={step.total ? { width: `${frac * 100}%` } : undefined} />
          </div>
        )}
        {step.detail && step.status !== 'pending' && (
          <small className="num" dir="ltr">
            {step.detail}
          </small>
        )}
      </div>
    </li>
  )
}
