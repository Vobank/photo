import { describe, expect, it } from 'vitest'

import en from './locales/en.json'
import ru from './locales/ru.json'

type Tree = { [k: string]: string | Tree }

/** Flatten to dotted keys, folding plural suffixes so languages with more forms still match. */
function keys(tree: Tree, prefix = ''): Set<string> {
  const out = new Set<string>()
  for (const [k, v] of Object.entries(tree)) {
    const path = prefix + k.replace(/_(zero|one|two|few|many|other)$/, '')
    if (typeof v === 'string') out.add(path)
    else for (const sub of keys(v, `${path}.`)) out.add(sub)
  }
  return out
}

function placeholders(tree: Tree, prefix = ''): Map<string, string> {
  const out = new Map<string, string>()
  for (const [k, v] of Object.entries(tree)) {
    const path = prefix + k
    if (typeof v === 'string') out.set(path, [...v.matchAll(/{{(\w+)}}/g)].map((m) => m[1]).sort().join(','))
    else for (const [p, s] of placeholders(v, `${path}.`)) out.set(p, s)
  }
  return out
}

describe('locales', () => {
  it('ru has exactly the keys en has', () => {
    expect([...keys(ru as Tree)].sort()).toEqual([...keys(en as Tree)].sort())
  })

  it('ru plurals cover one/few/many/other', () => {
    const flat = placeholders(ru as Tree)
    const plurals = [...flat.keys()].filter((k) => k.endsWith('_one')).map((k) => k.slice(0, -4))
    for (const base of plurals) {
      for (const form of ['few', 'many', 'other']) expect(flat.has(`${base}_${form}`), `${base}_${form}`).toBe(true)
    }
  })

  it('translations keep the same placeholders', () => {
    const e = placeholders(en as Tree)
    const r = placeholders(ru as Tree)
    for (const [key, vars] of r) {
      const base = key.replace(/_(few|many)$/, '_other')
      if (e.has(base)) expect(vars, key).toBe(e.get(base))
    }
  })
})
