import { useSyncExternalStore } from 'react'

/** Minimal history-API router: four top-level views don't justify a dependency. */

export type View = 'studio' | 'gallery' | 'models' | 'settings'

export interface Route {
  view: View
  imageId: string | null
}

const VIEWS: readonly View[] = ['studio', 'gallery', 'models', 'settings']

export function parse(pathname: string): Route {
  const [first = '', second = null] = pathname.split('/').filter(Boolean)
  const view = (VIEWS as readonly string[]).includes(first) ? (first as View) : 'studio'
  return { view, imageId: view === 'gallery' ? second : null }
}

export function toPath(route: Route): string {
  if (route.view === 'studio') return '/'
  return route.imageId ? `/${route.view}/${route.imageId}` : `/${route.view}`
}

const listeners = new Set<() => void>()
let current = parse(location.pathname)

window.addEventListener('popstate', () => {
  current = parse(location.pathname)
  listeners.forEach((l) => l())
})

export function navigate(route: Partial<Route> & { view: View }, opts: { replace?: boolean } = {}) {
  const next: Route = { imageId: null, ...route }
  const path = toPath(next)
  if (path !== location.pathname) {
    history[opts.replace ? 'replaceState' : 'pushState'](null, '', path)
  }
  current = next
  listeners.forEach((l) => l())
}

export function useRoute(): Route {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    () => current,
  )
}
