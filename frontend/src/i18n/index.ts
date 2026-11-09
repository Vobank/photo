import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import en from './locales/en.json'

/** Interface languages, in the order shown to users. Keep in sync with backend config.LANGUAGES. */
export const LANGUAGES = [
  { id: 'en', label: 'English' },
  { id: 'zh-CN', label: '简体中文' },
  { id: 'es', label: 'Español' },
  { id: 'pt-BR', label: 'Português (Brasil)' },
  { id: 'fr', label: 'Français' },
  { id: 'de', label: 'Deutsch' },
  { id: 'it', label: 'Italiano' },
  { id: 'ru', label: 'Русский' },
  { id: 'ja', label: '日本語' },
  { id: 'ko', label: '한국어' },
  { id: 'tr', label: 'Türkçe' },
  { id: 'ar', label: 'العربية', dir: 'rtl' },
] as const satisfies readonly { id: string; label: string; dir?: 'rtl' }[]

export type LanguageId = (typeof LANGUAGES)[number]['id']
export const DEFAULT_LANGUAGE: LanguageId = 'en'
const STORAGE_KEY = 'photo.lang'

export const isLanguage = (v: unknown): v is LanguageId => LANGUAGES.some((l) => l.id === v)

// Every locale except English is a separate chunk, fetched only when chosen.
const loaders = import.meta.glob<{ default: Record<string, unknown> }>(['./locales/*.json', '!./locales/en.json'])

// Scripts IBM Plex Sans (Latin/Cyrillic) does not cover get their own Plex family on demand.
const fontLoaders: Partial<Record<LanguageId, () => Promise<unknown>>> = {
  ja: () => Promise.all([import('@fontsource/ibm-plex-sans-jp/400.css'), import('@fontsource/ibm-plex-sans-jp/500.css'), import('@fontsource/ibm-plex-sans-jp/600.css')]),
  ko: () => Promise.all([import('@fontsource/ibm-plex-sans-kr/400.css'), import('@fontsource/ibm-plex-sans-kr/500.css'), import('@fontsource/ibm-plex-sans-kr/600.css')]),
  ar: () => Promise.all([import('@fontsource/ibm-plex-sans-arabic/400.css'), import('@fontsource/ibm-plex-sans-arabic/500.css'), import('@fontsource/ibm-plex-sans-arabic/600.css')]),
}

function storedLanguage(): LanguageId | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return isLanguage(v) ? v : null
  } catch {
    return null
  }
}

/** True once the user picked a language on this device (it then wins over the server's). */
export const hasLocalChoice = () => storedLanguage() !== null

function applyDocument(lng: string) {
  const meta = LANGUAGES.find((l) => l.id === lng)
  document.documentElement.lang = lng
  document.documentElement.dir = meta && 'dir' in meta ? meta.dir : 'ltr'
}

/** Load (if needed) and switch to ``lng``. Unknown ids fall back to English. */
export async function setLanguage(lng: string, opts: { remember?: boolean } = {}): Promise<void> {
  const id: LanguageId = isLanguage(lng) ? lng : DEFAULT_LANGUAGE
  if (id !== 'en' && !i18n.hasResourceBundle(id, 'translation')) {
    const loader = loaders[`./locales/${id}.json`]
    if (loader) i18n.addResourceBundle(id, 'translation', (await loader()).default, true, true)
  }
  await fontLoaders[id]?.()
  await i18n.changeLanguage(id)
  if (opts.remember) {
    try {
      localStorage.setItem(STORAGE_KEY, id)
    } catch {
      /* storage unavailable: choice lasts for this session */
    }
  }
}

i18n.on('languageChanged', applyDocument)

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en } },
  lng: DEFAULT_LANGUAGE,
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: LANGUAGES.map((l) => l.id),
  interpolation: { escapeValue: false }, // React already escapes
  returnNull: false,
})
applyDocument(DEFAULT_LANGUAGE)

/** Language to start with before the server answers: this device's choice, else English. */
export const initialLanguage = storedLanguage() ?? DEFAULT_LANGUAGE
if (initialLanguage !== DEFAULT_LANGUAGE) void setLanguage(initialLanguage)

export default i18n
