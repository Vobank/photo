import type { ServerEvent } from './types'

export interface PreviewFrame {
  jobId: string
  blob: Blob
}

export interface EventHandlers {
  onEvent: (event: ServerEvent) => void
  onPreview: (frame: PreviewFrame) => void
  onConnection: (connected: boolean) => void
}

/** Decodes the binary preview frame: uint32 BE header length · JSON header · image. */
export function decodePreview(buf: ArrayBuffer): PreviewFrame | null {
  if (buf.byteLength < 4) return null
  const headerLen = new DataView(buf).getUint32(0, false)
  if (4 + headerLen > buf.byteLength) return null
  try {
    const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, headerLen))) as {
      job_id: string
      mime: string
    }
    return { jobId: header.job_id, blob: new Blob([buf.slice(4 + headerLen)], { type: header.mime }) }
  } catch {
    return null
  }
}

/**
 * Keeps one WebSocket open to /api/v1/events, reconnecting with capped backoff.
 * Returns a function that closes it for good.
 */
export function connectEvents(handlers: EventHandlers): () => void {
  let ws: WebSocket | null = null
  let closed = false
  let attempt = 0
  let timer: ReturnType<typeof setTimeout> | undefined

  const open = () => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/api/v1/events`)
    ws.binaryType = 'arraybuffer'

    ws.onopen = () => {
      attempt = 0
      handlers.onConnection(true)
    }
    ws.onmessage = (msg: MessageEvent<string | ArrayBuffer>) => {
      if (typeof msg.data === 'string') {
        try {
          handlers.onEvent(JSON.parse(msg.data) as ServerEvent)
        } catch {
          /* ignore malformed frame */
        }
      } else {
        const frame = decodePreview(msg.data)
        if (frame) handlers.onPreview(frame)
      }
    }
    ws.onclose = () => {
      handlers.onConnection(false)
      if (closed) return
      const delay = Math.min(500 * 2 ** attempt, 8000)
      attempt += 1
      timer = setTimeout(open, delay)
    }
  }

  // Reconnect immediately when the tab becomes visible again (laptop wake, etc.).
  const onVisible = () => {
    if (document.visibilityState === 'visible' && ws?.readyState === WebSocket.CLOSED) {
      clearTimeout(timer)
      attempt = 0
      open()
    }
  }
  document.addEventListener('visibilitychange', onVisible)
  open()

  return () => {
    closed = true
    clearTimeout(timer)
    document.removeEventListener('visibilitychange', onVisible)
    ws?.close()
  }
}
