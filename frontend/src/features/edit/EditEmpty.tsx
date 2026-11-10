import { FolderOpen } from '@phosphor-icons/react'
import { useRef } from 'react'
import { useTranslation } from 'react-i18next'

import { Button } from '../../components/Button'
import { useOpenFiles } from './openFiles'
import styles from './Edit.module.css'

/** Edit mode before a picture is chosen. */
export function EditEmpty() {
  const { t } = useTranslation()
  const fileRef = useRef<HTMLInputElement>(null)
  const { open, busy } = useOpenFiles()
  return (
    <div className={styles.stage}>
      <div className={styles.empty}>
        <strong>{t('edit.emptyTitle')}</strong>
        <span>{t('edit.emptyBody')}</span>
        <Button variant="primary" icon={<FolderOpen size={16} />} disabled={busy} onClick={() => fileRef.current?.click()}>
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
  )
}
