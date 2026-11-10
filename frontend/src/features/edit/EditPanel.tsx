import { FolderOpen } from '@phosphor-icons/react'
import { useEffect, useId, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, thumbUrl, uploadThumbUrl } from '../../api/client'
import { Button } from '../../components/Button'
import fieldStyles from '../../components/Field.module.css'
import { Segmented } from '../../components/Segmented'
import { toastError } from '../../components/toast'
import { apiErrorText } from '../../lib/errors'
import { isMac } from '../../lib/format'
import { type EditAction, type HideMode, useEdit } from '../../state/edit'
import { useLive } from '../../state/live'
import { ModeSwitch } from './ModeSwitch'
import { useOpenFiles } from './openFiles'
import styles from './Edit.module.css'
import { missingForApply } from './logic'

const PROMPT_MAX = 4000
const EXAMPLES = ['example1', 'example2', 'example3', 'example4'] as const

export function EditPanel() {
  const { t, i18n } = useTranslation()
  const s = useEdit()
  const upsertJob = useLive((st) => st.upsertJob)
  const [sending, setSending] = useState(false)
  const promptId = useId()
  const fileRef = useRef<HTMLInputElement>(null)
  const { open, busy: uploading } = useOpenFiles()

  const job = useLive((st) => (s.pendingJobId ? st.jobs[s.pendingJobId] : undefined))
  const running = !!job && (job.status === 'queued' || job.status === 'running' || job.status === 'succeeded')
  const prompt = s.action === 'hide' ? '' : s.prompts[s.action]
  const missing = missingForApply({ action: s.action, prompt, selected: s.selected, hasSource: !!s.source })
  const canApply = !missing && !sending && !running

  const apply = async () => {
    const st = useEdit.getState()
    const text = st.action === 'hide' ? '' : st.prompts[st.action].trim()
    if (missingForApply({ action: st.action, prompt: text, selected: st.selected, hasSource: !!st.source }) || !st.source) return
    setSending(true)
    try {
      const maskId = st.selected > 0 && st.mask ? (await api.upload(await st.mask.toPng())).id : null
      const created = await api.createJob({
        kind: 'edit',
        model: 'auto',
        source: st.source.id,
        mask: maskId,
        action: st.action === 'hide' ? st.hideMode : st.action,
        prompt: text,
        batch_size: st.action === 'hide' ? 1 : st.batch,
      })
      upsertJob(created)
      st.set({ pendingJobId: created.id })
    } catch (e) {
      toastError(apiErrorText(t, e))
    } finally {
      setSending(false)
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault()
        void apply()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const pct = new Intl.NumberFormat(i18n.language, { style: 'percent', maximumFractionDigits: s.selected < 0.01 ? 1 : 0 })
  const selectionState = s.selected > 0 ? 'selected' : missing === 'selection' ? 'needed' : 'none'
  const usesModel = s.action !== 'hide'

  return (
    <aside className={styles.panel} aria-label={t('edit.panel')}>
      <div className={styles.body}>
        <ModeSwitch />

        <div className={styles.section}>
          <div className={styles.title}>{t('edit.picture')}</div>
          <div className={styles.sourceRow}>
            {s.source && <img src={s.source.kind === 'image' ? thumbUrl(s.source.id) : uploadThumbUrl(s.source.id)} alt="" />}
            <div style={{ flex: 1, minWidth: 0 }}>
              {s.source ? (
                <>
                  <span className="num">
                    {s.source.width} × {s.source.height}
                  </span>
                  {s.history.length > 0 && <small>{t('edit.versions', { count: s.history.length })}</small>}
                </>
              ) : (
                <small>{t('edit.noPicture')}</small>
              )}
            </div>
            <Button size="sm" icon={<FolderOpen size={14} />} onClick={() => fileRef.current?.click()} disabled={uploading}>
              {t('edit.open')}
            </Button>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              hidden
              onChange={(e) => {
                if (e.target.files) void open(e.target.files)
                e.target.value = ''
              }}
            />
          </div>
        </div>

        <div className={styles.section}>
          <div className={styles.title}>{t('edit.action')}</div>
          <Segmented<EditAction>
            label={t('edit.action')}
            value={s.action}
            options={[
              { value: 'edit', label: t('edit.actions.edit') },
              { value: 'remove', label: t('edit.actions.remove') },
              { value: 'hide', label: t('edit.actions.hide') },
            ]}
            onChange={(action) => s.set({ action })}
          />
          {s.action === 'hide' && (
            <Segmented<HideMode>
              label={t('edit.hideMode')}
              value={s.hideMode}
              options={[
                { value: 'blur', label: t('edit.hide.blur') },
                { value: 'pixelate', label: t('edit.hide.pixelate') },
                { value: 'fill', label: t('edit.hide.fill') },
              ]}
              onChange={(hideMode) => s.set({ hideMode })}
            />
          )}
        </div>

        <div className={styles.selectionNote} data-state={selectionState} role="status">
          <span className={styles.dot} aria-hidden />
          <span>
            {s.selected > 0
              ? t('edit.selected', { share: pct.format(s.selected) })
              : s.action === 'edit'
                ? t('edit.noSelectionWhole')
                : t('edit.selectFirst')}
          </span>
        </div>

        {usesModel && (
          <div className={styles.section}>
            <label htmlFor={promptId} className={fieldStyles.label}>
              {s.action === 'remove' ? t('edit.whatToRemove') : t('edit.whatToDo')}
              {s.action === 'remove' && <span className={fieldStyles.hint}>{t('edit.optional')}</span>}
            </label>
            <textarea
              id={promptId}
              className={fieldStyles.textarea}
              rows={3}
              maxLength={PROMPT_MAX}
              placeholder={s.action === 'remove' ? t('edit.removePlaceholder') : t('edit.promptPlaceholder')}
              value={prompt}
              onChange={(e) => s.setPrompt(e.target.value)}
            />
            {s.action === 'edit' && !prompt && (
              <div className={styles.examples}>
                {EXAMPLES.map((key) => (
                  <button key={key} type="button" className={styles.example} onClick={() => s.setPrompt(t(`edit.${key}`))}>
                    {t(`edit.${key}`)}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {usesModel && (
          <div className={styles.section}>
            <div className={styles.title}>{t('edit.variants')}</div>
            <Segmented<number>
              label={t('edit.variants')}
              value={s.batch}
              options={[1, 2, 3, 4].map((n) => ({ value: n, label: String(n) }))}
              onChange={(batch) => s.set({ batch })}
            />
          </div>
        )}
      </div>

      <div className={styles.footer}>
        <Button variant="primary" size="lg" disabled={!canApply} onClick={() => void apply()}>
          {running || sending ? t('edit.working') : t('edit.apply')}
        </Button>
        <div className={styles.footerHint}>
          <span>{missing && s.source ? t(`edit.missing.${missing}`) : ' '}</span>
          <kbd className="num">{isMac() ? '⌘' : 'Ctrl'} + Enter</kbd>
        </div>
      </div>
    </aside>
  )
}
