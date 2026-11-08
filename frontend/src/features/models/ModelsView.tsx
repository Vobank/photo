import { useTranslation } from 'react-i18next'

import { useModels, useSystem } from '../../api/queries'
import { formatBytes } from '../../lib/format'
import { ModelInstallLine } from '../studio/Onboarding'
import styles from '../settings/Page.module.css'

export default function ModelsView() {
  const { t, i18n } = useTranslation()
  const { data: models } = useModels()
  const { data: system } = useSystem()

  return (
    <div className={styles.page}>
      <div className={styles.column}>
        <header className={styles.head}>
          <h1>{t('models.title')}</h1>
          {system?.gpu && (
            <p>
              {t('models.gpuLine', {
                gpu: system.gpu.name,
                vram: system.gpu.vram_gb,
                arch: system.gpu.arch === 'blackwell' ? 'RTX 50' : system.gpu.arch === 'ada' ? 'RTX 40' : system.gpu.arch,
              })}
            </p>
          )}
        </header>

        {models?.map((m) => (
          <section key={m.id} className={styles.card}>
            <div className={styles.cardHead}>
              <div>
                <h2>{m.name}</h2>
                <span className={styles.muted}>{m.vendor}</span>
              </div>
              <a className={styles.license} href={m.license_url} target="_blank" rel="noreferrer noopener">
                {m.license}
                {m.commercial_use ? ` · ${t('models.commercialOk')}` : ` · ${t('models.nonCommercial')}`}
              </a>
            </div>
            <p className={styles.muted}>{m.description}</p>
            {m.installed ? (
              <table className={styles.table}>
                <tbody>
                  {m.variants.map((v) => (
                    <tr key={v.id}>
                      <td>{v.label}</td>
                      <td className="num">{formatBytes(v.total_bytes, i18n.language)}</td>
                      <td>
                        {v.installed ? t('models.installed') : v.recommended ? t('models.recommended') : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <ModelInstallLine model={m} />
            )}
          </section>
        ))}
        {system && (
          <p className={styles.muted}>
            {t('models.location')} <code className="num">{system.models_dir}</code>
          </p>
        )}
      </div>
    </div>
  )
}
