import * as Tooltip from '@radix-ui/react-tooltip'
import { QueryClientProvider, useQuery } from '@tanstack/react-query'
import { Suspense, lazy, useEffect } from 'react'

import { api } from '../api/client'
import { keys, queryClient, useServerMode } from '../api/queries'
import { Toasts } from '../components/Toasts'
import { StudioView } from '../features/studio/StudioView'
import i18n, { hasLocalChoice, setLanguage } from '../i18n'
import { useRoute } from '../lib/router'
import { AppShell } from './AppShell'
import { useEventStream } from './useEventStream'

const GalleryView = lazy(() => import('../features/gallery/GalleryView'))
const ModelsView = lazy(() => import('../features/models/ModelsView'))
const SettingsView = lazy(() => import('../features/settings/SettingsView'))
const SetupWizard = lazy(() => import('../features/setup/SetupWizard'))

/** Follow the language chosen in the installer unless this device picked its own. */
function useServerLanguage() {
  const { data: system } = useQuery({ queryKey: keys.system, queryFn: api.system })
  useEffect(() => {
    if (system && !hasLocalChoice() && system.language !== i18n.language) void setLanguage(system.language)
  }, [system])
}

function Views() {
  useEventStream()
  useServerLanguage()
  const route = useRoute()
  const { data: mode } = useServerMode()
  // Render nothing until we know whether this is the app or the installer: no flash.
  if (!mode) return null
  if (mode === 'setup') {
    return (
      <Suspense fallback={null}>
        <SetupWizard />
      </Suspense>
    )
  }
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
