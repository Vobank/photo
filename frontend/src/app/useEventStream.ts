import { useEffect } from 'react'

import { connectEvents } from '../api/events'
import { keys, patchCachedImage, queryClient } from '../api/queries'
import type { SetupSystemInfo, SystemInfo } from '../api/types'
import { useLive } from '../state/live'

/** Wires the server event socket into the live store and the query cache. */
export function useEventStream() {
  useEffect(() => {
    const live = useLive.getState()
    return connectEvents({
      onConnection: (connected) => {
        live.setConnected(connected)
        // Anything could have changed while we were disconnected.
        if (connected) void queryClient.invalidateQueries()
      },
      onPreview: ({ jobId, blob }) => live.setPreview(jobId, blob),
      onEvent: (event) => {
        live.apply(event)
        switch (event.type) {
          case 'image':
            void queryClient.invalidateQueries({ queryKey: ['images'] })
            break
          case 'image_deleted':
            patchCachedImage(queryClient, event.image_id, null)
            break
          case 'engine':
            queryClient.setQueryData<SystemInfo | SetupSystemInfo>(keys.system, (s) =>
              s?.mode === 'app' ? { ...s, engine: { state: event.state, error: event.error } } : s,
            )
            break
          case 'model_install':
            if (event.finished) void queryClient.invalidateQueries({ queryKey: keys.models })
            break
        }
      },
    })
  }, [])
}
