import { imageUrl, uploadFileUrl } from '../../api/client'
import type { EditAction, EditSource } from '../../state/edit'

export const sourceUrl = (s: Pick<EditSource, 'id' | 'kind'>) => (s.kind === 'image' ? imageUrl(s.id) : uploadFileUrl(s.id))

/** What a request needs before it can be sent; null when it is ready. */
export function missingForApply(s: { action: EditAction; prompt: string; selected: number; hasSource: boolean }): string | null {
  if (!s.hasSource) return 'source'
  if (s.action === 'edit' && !s.prompt.trim()) return 'prompt'
  if (s.action === 'hide' && s.selected <= 0) return 'selection'
  if (s.action === 'remove' && s.selected <= 0 && !s.prompt.trim()) return 'selection'
  return null
}

