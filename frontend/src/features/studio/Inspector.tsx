import { ArrowsClockwise, CaretRight, LockSimple, LockSimpleOpen } from '@phosphor-icons/react'
import { useMutation } from '@tanstack/react-query'
import { useEffect, useId, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'

import { api } from '../../api/client'
import { useModels } from '../../api/queries'
import { Button, IconButton } from '../../components/Button'
import fieldStyles from '../../components/Field.module.css'
import { NumberField } from '../../components/NumberField'
import { Segmented } from '../../components/Segmented'
import { toastError } from '../../components/toast'
import { ASPECTS, SIZES, dimensionsFor, megapixels } from '../../lib/dimensions'
import { apiErrorText } from '../../lib/errors'
import { isMac } from '../../lib/format'
import { activeJobs, useLive } from '../../state/live'
import { MAX_SEED, useStudio } from '../../state/studio'
import styles from './Studio.module.css'

const PROMPT_MAX = 4000

export function Inspector() {
  const { t, i18n } = useTranslation()
  const s = useStudio()
  const { data: models } = useModels()
  const installed = useMemo(
    () => models?.filter((m) => m.installed && m.tasks.includes('generate')) ?? [],
    [models],
  )
  const model = installed.find((m) => m.id === s.model)
  const queued = useLive((st) => activeJobs(st.jobs).length)
  const upsertJob = useLive((st) => st.upsertJob)
  const promptRef = useRef<HTMLTextAreaElement>(null)
  const promptId = useId()
  const negativeId = useId()
  const modelId = useId()

  // Pick a model automatically when the stored one is gone or none was chosen yet.
  const setStudio = s.set
  useEffect(() => {
    if (installed.length && !model) setStudio({ model: installed[0].id })
  }, [installed, model, setStudio])

  const create = useMutation({
    mutationFn: api.createJob,
    onSuccess: (job) => {
      upsertJob(job)
      useStudio.getState().set({ selectedImageId: null })
      if (!useStudio.getState().seedLocked) useStudio.getState().randomizeSeed()
    },
    onError: (err) => toastError(apiErrorText(t, err)),
  })

  const params = s.toParams()
  const canSubmit = !!params && !create.isPending

  const submit = () => {
    const p = useStudio.getState().toParams()
    if (p) create.mutate(p)
    else promptRef.current?.focus()
  }

  // Ctrl/Cmd+Enter generates from anywhere in the studio.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault()
        submit()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const dims = dimensionsFor(s.aspect, s.size)
  const nf = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 })

  return (
    <aside className={styles.inspector} aria-label={t('studio.settings')}>
      <div className={styles.inspectorBody}>
        <div className={styles.section}>
          <label htmlFor={promptId} className={fieldStyles.label}>
            {t('studio.prompt')}
          </label>
          <div className={styles.promptWrap}>
            <textarea
              id={promptId}
              ref={promptRef}
              className={fieldStyles.textarea}
              rows={5}
              maxLength={PROMPT_MAX}
              placeholder={t('studio.promptPlaceholder')}
              value={s.prompt}
              onChange={(e) => s.set({ prompt: e.target.value })}
              spellCheck
            />
            {s.prompt.length > PROMPT_MAX * 0.8 && (
              <span className={`${styles.promptCount} num`}>
                {s.prompt.length}/{PROMPT_MAX}
              </span>
            )}
          </div>
        </div>

        <div className={styles.section}>
          <label htmlFor={modelId} className={fieldStyles.label}>
            {t('studio.model')}
          </label>
          <select
            id={modelId}
            className={fieldStyles.select}
            value={s.model ?? ''}
            onChange={(e) => s.set({ model: e.target.value, steps: null, cfg: null })}
            disabled={!installed.length}
          >
            {!installed.length && <option value="">{t('studio.noModels')}</option>}
            {installed.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </div>

        <div className={styles.divider} />

        <div className={styles.section}>
          <div className={styles.sectionTitle}>
            <span id="aspect-label">{t('studio.aspect')}</span>
          </div>
          <div role="radiogroup" aria-labelledby="aspect-label" className={styles.aspects}>
            {ASPECTS.map((a) => {
              const scale = 22 / Math.max(a.w, a.h)
              return (
                <button
                  key={a.id}
                  type="button"
                  role="radio"
                  aria-checked={s.aspect === a.id}
                  className={styles.aspect}
                  onClick={() => s.set({ aspect: a.id })}
                >
                  <span
                    className={styles.aspectShape}
                    style={{ width: a.w * scale, height: a.h * scale }}
                    aria-hidden
                  />
                  {a.id}
                </button>
              )
            })}
          </div>
        </div>

        <div className={styles.section}>
          <div className={styles.sectionTitle}>{t('studio.size')}</div>
          <Segmented
            label={t('studio.size')}
            value={s.size}
            options={SIZES.map((x) => ({ value: x.id, label: t(`studio.sizes.${x.id}`) }))}
            onChange={(size) => s.set({ size })}
          />
          <div className={`${styles.dims} num`}>
            <span>
              {dims.width} × {dims.height}
            </span>
            <span>{nf.format(megapixels(dims.width, dims.height))} MP</span>
          </div>
        </div>

        <div className={styles.section}>
          <div className={styles.sectionTitle}>{t('studio.count')}</div>
          <Segmented
            label={t('studio.count')}
            value={s.batch}
            options={[1, 2, 3, 4].map((n) => ({ value: n, label: String(n) }))}
            onChange={(batch) => s.set({ batch })}
          />
        </div>

        <div className={styles.section}>
          <div className={styles.sectionTitle}>{t('studio.seed')}</div>
          <div className={styles.seedRow}>
            <input
              aria-label={t('studio.seed')}
              className={`${fieldStyles.input} num`}
              inputMode="numeric"
              value={s.seedLocked ? String(s.seed) : ''}
              placeholder={t('studio.seedRandom')}
              onChange={(e) => {
                const digits = e.target.value.replace(/\D/g, '')
                if (!digits) return s.set({ seedLocked: false })
                s.set({ seed: Math.min(Number(digits), MAX_SEED), seedLocked: true })
              }}
            />
            <IconButton
              label={s.seedLocked ? t('studio.seedUnlock') : t('studio.seedLock')}
              active={s.seedLocked}
              onClick={() => s.set({ seedLocked: !s.seedLocked })}
            >
              {s.seedLocked ? <LockSimple size={16} /> : <LockSimpleOpen size={16} />}
            </IconButton>
            <IconButton
              label={t('studio.seedNew')}
              onClick={() => s.set({ seedLocked: true, seed: Math.floor(Math.random() * MAX_SEED) })}
            >
              <ArrowsClockwise size={16} />
            </IconButton>
          </div>
        </div>

        <div className={styles.section}>
          <button
            type="button"
            className={styles.advancedToggle}
            aria-expanded={s.advancedOpen}
            onClick={() => s.set({ advancedOpen: !s.advancedOpen })}
          >
            <CaretRight size={12} weight="bold" />
            {t('studio.advanced')}
          </button>
          {s.advancedOpen && (
            <>
              <NumberField
                label={t('studio.steps')}
                value={s.steps}
                placeholder={model?.defaults.steps}
                min={1}
                max={100}
                onChange={(steps) => s.set({ steps })}
              />
              <NumberField
                label={t('studio.cfg')}
                value={s.cfg}
                placeholder={model?.defaults.cfg}
                min={0}
                max={30}
                step={0.1}
                dragPixelsPerStep={3}
                onChange={(cfg) => s.set({ cfg })}
              />
              <label htmlFor={negativeId} className={fieldStyles.label}>
                {t('studio.negative')}
                <span className={fieldStyles.hint}>{t('studio.negativeHint')}</span>
              </label>
              <textarea
                id={negativeId}
                className={fieldStyles.textarea}
                rows={2}
                style={{ minHeight: 56 }}
                maxLength={PROMPT_MAX}
                value={s.negativePrompt}
                onChange={(e) => s.set({ negativePrompt: e.target.value })}
              />
            </>
          )}
        </div>
      </div>

      <div className={styles.footer}>
        <Button
          variant="primary"
          size="lg"
          className={styles.generate}
          disabled={!canSubmit}
          onClick={submit}
        >
          {s.batch > 1 ? t('studio.generateN', { count: s.batch }) : t('studio.generate')}
        </Button>
        <div className={styles.footerHint}>
          <span>{queued > 0 ? t('status.queue', { count: queued }) : ' '}</span>
          <kbd className="num">{isMac() ? '⌘' : 'Ctrl'} + Enter</kbd>
        </div>
      </div>
    </aside>
  )
}
