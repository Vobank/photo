import { useModels } from '../../api/queries'
import { Canvas } from './Canvas'
import { Filmstrip } from './Filmstrip'
import { Inspector } from './Inspector'
import { Onboarding } from './Onboarding'
import styles from './Studio.module.css'

export function StudioView() {
  const { data: models } = useModels()
  const ready = models?.some((m) => m.installed)

  return (
    <div className={styles.studio}>
      <section className={styles.stage}>
        {models && !ready ? <Onboarding models={models} /> : <Canvas />}
        <Filmstrip />
      </section>
      <Inspector />
    </div>
  )
}
