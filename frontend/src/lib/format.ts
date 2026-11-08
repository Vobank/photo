export function formatBytes(bytes: number, locale: string): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = bytes
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000
    i += 1
  }
  const digits = v >= 100 || i === 0 ? 0 : 1
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(v)} ${units[i]}`
}

export function formatDuration(seconds: number, locale: string): string {
  const fmt = new Intl.NumberFormat(locale, { maximumFractionDigits: seconds < 10 ? 1 : 0 })
  if (seconds < 60) return `${fmt.format(seconds)} s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

export function formatRelative(epochSeconds: number, locale: string): string {
  const diff = epochSeconds - Date.now() / 1000
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
  const abs = Math.abs(diff)
  if (abs < 60) return rtf.format(Math.round(diff), 'second')
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour')
  if (abs < 86400 * 7) return rtf.format(Math.round(diff / 86400), 'day')
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(epochSeconds * 1000)
}

export const isMac = () => /Mac|iPhone|iPad/.test(navigator.platform)
