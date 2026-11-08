import * as Tooltip from '@radix-ui/react-tooltip'
import { QueryClientProvider } from '@tanstack/react-query'
import { Suspense, lazy } from 'react'

import { queryClient } from '../api/queries'
import { Toasts } from '../components/Toasts'
import { StudioView } from '../features/studio/StudioView'
import { useRoute } from '../lib/router'
import { AppShell } from './AppShell'
import { useEventStream } from './useEventStream'

const GalleryView = lazy(() => import('../features/gallery/GalleryView'))
const ModelsView = lazy(() => import('../features/models/ModelsView'))
const SettingsView = lazy(() => import('../features/settings/SettingsView'))

function Views() {
  useEventStream()
  const route = useRoute()
  return (
    <AppShell view={route.view}>
      <Suspense fallback={null}>
        {route.view === 'studio' && <StudioView />}
        {route.view === 'gallery' && <GalleryView imageId={route.imageId} />}
        {route.view === 'models' && <ModelsView />}
        {route.view === 'settings' && <SettingsView />}
      </Suspense>
    </AppShell>
  )
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Tooltip.Provider delayDuration={500} skipDelayDuration={200}>
        <Views />
        <Toasts />
      </Tooltip.Provider>
    </QueryClientProvider>
  )
}
