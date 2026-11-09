import {
  type InfiniteData,
  QueryClient,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import { api } from './client'
import type { ImageInfo } from './types'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Live updates arrive over the event socket, so polling is unnecessary.
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})

export const keys = {
  system: ['system'] as const,
  models: ['models'] as const,
  images: (favorites: boolean) => ['images', { favorites }] as const,
  image: (id: string) => ['image', id] as const,
}

/** App-mode system info; undefined while the setup wizard is being served. */
export const useSystem = () =>
  useQuery({
    queryKey: keys.system,
    queryFn: api.system,
    select: (d) => (d.mode === 'app' ? d : undefined),
  })

/** Whether the server is the app or the setup wizard. */
export const useServerMode = () =>
  useQuery({ queryKey: keys.system, queryFn: api.system, select: (d) => d.mode })

export const useModels = () => useQuery({ queryKey: keys.models, queryFn: api.models })

export function useImages(favorites = false) {
  return useInfiniteQuery({
    queryKey: keys.images(favorites),
    queryFn: ({ pageParam }) => api.images({ before: pageParam, favorites }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next ?? undefined,
  })
}

export const useImage = (id: string | null) =>
  useQuery({ queryKey: keys.image(id ?? ''), queryFn: () => api.image(id!), enabled: !!id })

type ImagePages = InfiniteData<{ images: ImageInfo[]; next: string | null }>

/** Patch an image everywhere it is cached, without refetching. */
export function patchCachedImage(qc: QueryClient, id: string, patch: Partial<ImageInfo> | null) {
  qc.setQueriesData<ImagePages>({ queryKey: ['images'] }, (data) =>
    data
      ? {
          ...data,
          pages: data.pages.map((p) => ({
            ...p,
            images:
              patch === null
                ? p.images.filter((i) => i.id !== id)
                : p.images.map((i) => (i.id === id ? { ...i, ...patch } : i)),
          })),
        }
      : data,
  )
  if (patch) qc.setQueryData<ImageInfo>(keys.image(id), (old) => (old ? { ...old, ...patch } : old))
}

export function useToggleFavorite() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, favorite }: { id: string; favorite: boolean }) => api.setFavorite(id, favorite),
    onMutate: ({ id, favorite }) => patchCachedImage(qc, id, { favorite }),
    onError: (_e, { id, favorite }) => patchCachedImage(qc, id, { favorite: !favorite }),
    onSettled: () => qc.invalidateQueries({ queryKey: ['images', { favorites: true }] }),
  })
}
