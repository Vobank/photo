import { ImageSquare, Plus, X } from '@phosphor-icons/react'
import { type ChangeEvent, useId, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { ModelInfo } from '../../api/types'
import { IconButton } from '../../components/Button'
import { Segmented } from '../../components/Segmented'
import { MAX_REFERENCES, useStudio } from '../../state/studio'
import { pictureThumb, useAddFiles } from './inputs'
import { ModelInstallLine } from './Onboarding'
import styles from './Studio.module.css'

export function InputPictures({ models }: { models: ModelInfo[] }) {
  const { t } = useTranslation()
  const s = useStudio()
  const fileRef = useRef<HTMLInputElement>(null)
  const strengthId = useId()
  const { add, busy } = useAddFiles()
  const [dragging, setDragging] = useState(false)

  const max = s.inputMode === 'references' ? MAX_REFERENCES : 1
  const canAdd = s.inputs.length < max
  const needsReferenceModel =
    s.inputMode === 'references' && s.inputs.length > 0 && !models.some((m) => m.installed && m.features.references)
  const referenceModel = models.find((m) => m.features.references)

  const onPick = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) void add(e.target.files)
    e.target.value = ''
  }

  return (
    <div className={styles.section}>
      <div className={styles.sectionTitle}>
        <span>{t('looks.pictures')}</span>
      </div>
      <Segmented
        label={t('looks.pictures')}
        value={s.inputMode}
        options={[
          { value: 'references', label: t('looks.modeReferences'), title: t('looks.modeReferencesHint') },
          { value: 'variation', label: t('looks.modeVariation'), title: t('looks.modeVariationHint') },
        ]}
        onChange={(inputMode) =>
          s.set({ inputMode, inputs: inputMode === 'variation' ? s.inputs.slice(0, 1) : s.inputs })
        }
      />

      <div
        className={styles.dropZone}
        data-dragging={dragging}
        data-empty={s.inputs.length === 0}
        onDragOver={(e) => {
          if (e.dataTransfer.types.includes('Files')) {
            e.preventDefault()
            setDragging(true)
          }
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          void add(e.dataTransfer.files)
        }}
      >
        {s.inputs.length === 0 ? (
          <button type="button" className={styles.dropEmpty} onClick={() => fileRef.current?.click()}>
            <ImageSquare size={20} aria-hidden />
            <span>{s.inputMode === 'references' ? t('looks.dropReferences') : t('looks.dropVariation')}</span>
            <small>{t('looks.dropHint')}</small>
          </button>
        ) : (
          <div className={styles.inputGrid}>
            {s.inputs.map((p) => (
              <div key={p.id} className={styles.inputThumb}>
                <img src={pictureThumb(p)} alt="" />
                <IconButton label={t('actions.remove')} className={styles.inputRemove} onClick={() => s.removeInput(p.id)}>
                  <X size={12} weight="bold" />
                </IconButton>
              </div>
            ))}
            {canAdd && (
              <button
                type="button"
                className={styles.inputAdd}
                aria-label={t('looks.addPicture')}
                onClick={() => fileRef.current?.click()}
              >
                <Plus size={16} />
              </button>
            )}
          </div>
        )}
        {busy && <span className={styles.uploading}>{t('looks.uploading')}</span>}
        <input ref={fileRef} type="file" accept="image/*" multiple={s.inputMode === 'references'} hidden onChange={onPick} />
      </div>

      {s.inputMode === 'variation' && s.inputs.length > 0 && (
        <div className={styles.strength}>
          <label htmlFor={strengthId}>{t('looks.closeness')}</label>
          <input
            id={strengthId}
            type="range"
            min={0.15}
            max={0.9}
            step={0.05}
            // The slider reads "close → loose", i.e. low → high strength.
            value={s.variationStrength}
            onChange={(e) => s.set({ variationStrength: Number(e.target.value) })}
          />
          <div className={styles.strengthLabels}>
            <span>{t('looks.close')}</span>
            <span>{t('looks.loose')}</span>
          </div>
        </div>
      )}

      {needsReferenceModel && referenceModel && (
        <div className={styles.needsModel}>
          <p>{t('looks.needsReferenceModel', { name: referenceModel.name })}</p>
          <ModelInstallLine model={referenceModel} />
        </div>
      )}
    </div>
  )
}
