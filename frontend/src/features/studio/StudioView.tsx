import { useEffect } from 'react'

import { useModels } from '../../api/queries'
import { Canvas } from './Canvas'
import { Filmstrip } from './Filmstrip'
import { useAddFiles } from './inputs'
import { Inspector } from './Inspector'
import { Onboarding } from './Onboarding'
import styles from './Studio.module.css'

export function StudioView() {
  const { data: models } = useModels()
  const ready = models?.some((m) => m.installed)
  const { add } = useAddFiles()

  // Paste a picture anywhere in the studio to use it as a reference.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const files = [...(e.clipboardData?.files ?? [])].filter((f) => f.type.startsWith('image/'))
      if (files.length) {
        e.preventDefault()
        void add(files)
      }
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [add])

  return (
    <div className={styles.studio}>
      <section
        className={styles.stage}
        onDragOver={(e) => e.dataTransfer.types.includes('Files') && e.preventDefault()}
        onDrop={(e) => {
          if (!e.dataTransfer.files.length) return
          e.preventDefault()
          void add(e.dataTransfer.files)
        }}
      >
        {models && !ready ? <Onboarding models={models} /> : <Canvas />}
        <Filmstrip />
      </section>
      <Inspector />
    </div>
  )
}
