import { describe, expect, it } from 'vitest'

import { decodePreview } from './events'

function frame(header: object, image: Uint8Array): ArrayBuffer {
  const h = new TextEncoder().encode(JSON.stringify(header))
  const buf = new Uint8Array(4 + h.length + image.length)
  new DataView(buf.buffer).setUint32(0, h.length, false)
  buf.set(h, 4)
  buf.set(image, 4 + h.length)
  return buf.buffer
}

describe('decodePreview', () => {
  it('decodes the header and image payload', async () => {
    const out = decodePreview(frame({ type: 'preview', job_id: 'j1', mime: 'image/jpeg' }, new Uint8Array([1, 2, 3])))
    expect(out?.jobId).toBe('j1')
    expect(out?.blob.type).toBe('image/jpeg')
    expect(new Uint8Array(await out!.blob.arrayBuffer())).toEqual(new Uint8Array([1, 2, 3]))
  })

  it('rejects truncated or malformed frames', () => {
    expect(decodePreview(new ArrayBuffer(2))).toBeNull()
    const bad = new Uint8Array(8)
    new DataView(bad.buffer).setUint32(0, 999, false)
    expect(decodePreview(bad.buffer)).toBeNull()
    const notJson = new Uint8Array([0, 0, 0, 2, 0x7b, 0x7b])
    expect(decodePreview(notJson.buffer)).toBeNull()
  })
})
