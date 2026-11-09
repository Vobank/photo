import { describe, expect, it } from 'vitest'

import { LANGUAGES } from '.'
import en from './locales/en.json'

type Tree = { [k: string]: string | Tree }

const files = import.meta.glob<{ default: Tree }>('./locales/*.json', { eager: true })
const locale = (id: string): Tree | undefined => files[`./locales/${id}.json`]?.default

const PLURAL = /_(zero|one|two|few|many|other)$/

/** Every leaf as dotted key → string. */
function flatten(tree: Tree, prefix = '', out = new Map<string, string>()): Map<string, string> {
  for (const [k, v] of Object.entries(tree)) {
    if (typeof v === 'string') out.set(prefix + k, v)
    else flatten(v, `${prefix}${k}.`, out)
  }
  return out
}

const baseKey = (k: string) => k.replace(PLURAL, '')
const vars = (s: string) => [...s.matchAll(/{{(\w+)}}/g)].map((m) => m[1]).sort().join(',')

const enFlat = flatten(en as Tree)
const enBases = new Set([...enFlat.keys()].map(baseKey))
const pluralBases = new Set([...enFlat.keys()].filter((k) => PLURAL.test(k)).map(baseKey))

describe('locales', () => {
  it('there is a file for every language and no stray files', () => {
    const ids = Object.keys(files).map((f) => f.slice('./locales/'.length, -'.json'.length)).sort()
    expect(ids).toEqual(LANGUAGES.map((l) => l.id).sort())
  })

  for (const { id } of LANGUAGES.filter((l) => l.id !== 'en')) {
    describe(id, () => {
      const tree = locale(id) ?? {}
      const flat = flatten(tree)

      it('has exactly the keys English has', () => {
        const bases = new Set([...flat.keys()].map(baseKey))
        expect([...enBases].filter((k) => !bases.has(k)), 'missing').toEqual([])
        expect([...bases].filter((k) => !enBases.has(k)), 'extra').toEqual([])
      })

      it('has every plural form the language needs', () => {
        const categories = new Intl.PluralRules(id).resolvedOptions().pluralCategories
        for (const base of pluralBases) {
          for (const c of categories) expect(flat.has(`${base}_${c}`), `${base}_${c}`).toBe(true)
        }
      })

      it('keeps placeholders intact and leaves nothing empty', () => {
        for (const [key, value] of flat) {
          expect(value.trim(), key).not.toBe('')
          const enValue = enFlat.get(key) ?? enFlat.get(`${baseKey(key)}_other`)
          if (enValue === undefined) continue
          // Plural forms may spell the number out (e.g. Arabic dual), so {{count}} is optional there.
          const strip = (v: string) => (PLURAL.test(key) ? v.split(',').filter((x) => x && x !== 'count').join(',') : v)
          expect(strip(vars(value)), key).toBe(strip(vars(enValue)))
        }
      })
    })
  }
})
