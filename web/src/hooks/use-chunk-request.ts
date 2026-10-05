/*
 *  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 */

import message from '@/components/ui/message';
import { PaginationProps } from '@/interfaces/antd-compat';
import { ResponseGetType, ResponseType } from '@/interfaces/database/base';
import { IChunk, IKnowledgeFile } from '@/interfaces/database/dataset';
import kbService from '@/services/knowledge-service';
import {
  CHUNK_MAX_PAGE_SIZE,
  CHUNK_PAGE_SIZE,
  ChunkListPage,
  flattenChunkPages,
  nextChunkPage,
} from '@/utils/chunk-list';
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { useDebounce } from 'ahooks';
import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  useGetPaginationWithRouter,
  useHandleSearchChange,
} from './logic-hooks';
import {
  useGetKnowledgeSearchParams,
  useSetPaginationParams,
} from './route-hook';

export interface IChunkListResult {
  searchString?: string;
  handleInputChange?: React.ChangeEventHandler<HTMLInputElement>;
  pagination: PaginationProps;
  setPagination?: (pagination: { page: number; pageSize?: number }) => void;
  available: number | undefined;
  handleSetAvailable: (available: number | undefined) => void;
  dataUpdatedAt?: number; // Timestamp when data was last updated - useful for cache busting
}

/**
 * Query keys for the chunk list, in one place.
 *
 * The list is read by three things that must agree: the paginated hook, the
 * continuous one, and the mutations that invalidate it. A literal array repeated
 * in four files is how an invalidation stops matching the query it was meant to
 * refresh.
 */
export const ChunkKeys = {
  all: ['fetchChunkList'] as const,
  list: (
    knowledgeId: string | undefined,
    documentId: string | undefined,
    filters: Record<string, unknown>,
  ) => ['fetchChunkList', knowledgeId, documentId, filters] as const,
  detail: (knowledgeId?: string, documentId?: string, chunkId?: string) =>
    ['fetchChunk', knowledgeId, documentId, chunkId] as const,
};

/**
 * The chunk list currently in the cache, whichever hook asked for it.
 *
 * Both shapes are read here because both are the SAME list: the paginated hook
 * stores one response, the continuous one stores the blocks it has loaded, and the
 * chunk highlight on the document preview needs the chunk itself rather than the
 * shape it arrived in.
 */
export const useSelectChunkList = ():
  | { data: IChunk[]; total: number; documentInfo: IKnowledgeFile }
  | undefined => {
  const queryClient = useQueryClient();
  const entries = queryClient.getQueriesData<unknown>({
    queryKey: ChunkKeys.all,
  });
  const cached = entries?.at(-1)?.[1] as
    | (Partial<ChunkListPage> & { pages?: ChunkListPage[] })
    | undefined;
  if (!cached) return undefined;
  if (Array.isArray(cached.pages)) {
    const loaded = flattenChunkPages(cached.pages);
    return {
      data: loaded.chunks,
      total: loaded.total,
      documentInfo: loaded.documentInfo,
    };
  }
  return {
    data: cached.data ?? [],
    total: cached.total ?? 0,
    documentInfo: cached.documentInfo ?? ({} as IKnowledgeFile),
  };
};

export const useDeleteChunk = () => {
  const queryClient = useQueryClient();
  const { setPaginationParams } = useSetPaginationParams();
  const { knowledgeId } = useGetKnowledgeSearchParams();
  const {
    data,
    isPending: loading,
    mutateAsync,
  } = useMutation({
    mutationKey: ['deleteChunk'],
    mutationFn: async (params: { chunkIds: string[]; doc_id: string }) => {
      const { data } = await kbService.rmChunk({
        ...params,
        kb_id: knowledgeId,
      });
      if (data.code === 0) {
        setPaginationParams(1);
        queryClient.invalidateQueries({ queryKey: ChunkKeys.all });
      }
      return data?.code;
    },
  });

  return { data, loading, deleteChunk: mutateAsync };
};

export const useCreateChunk = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { knowledgeId } = useGetKnowledgeSearchParams();

  const {
    data,
    isPending: loading,
    mutateAsync,
  } = useMutation({
    mutationKey: ['createChunk'],
    mutationFn: async (payload: any) => {
      let service = kbService.createChunk;
      if (payload.chunk_id) {
        service = kbService.setChunk;
      }
      const { data } = await service({
        ...payload,
        kb_id: payload.kb_id || knowledgeId,
      });
      if (data.code === 0) {
        message.success(t('message.created'));
        setTimeout(() => {
          queryClient.invalidateQueries({ queryKey: ChunkKeys.all });
        }, 1000); // Delay to ensure the list is updated
      }
      return data?.code;
    },
  });

  return { data, loading, createChunk: mutateAsync };
};

export const useFetchChunk = (
  chunkId?: string,
  documentId?: string,
): ResponseType<any> => {
  const { knowledgeId } = useGetKnowledgeSearchParams();
  const { data } = useQuery({
    queryKey: ChunkKeys.detail(knowledgeId, documentId, chunkId),
    enabled: !!chunkId && !!documentId && !!knowledgeId,
    initialData: {},
    gcTime: 0,
    queryFn: async () => {
      const data = await kbService.getChunk({
        kb_id: knowledgeId,
        doc_id: documentId,
        chunk_id: chunkId,
      });

      return data;
    },
  });

  return data;
};

export const useFetchNextChunkList = (
  enabled = true,
  options?: { chunkIds?: string[] },
): ResponseGetType<{
  data: IChunk[];
  total: number;
  documentInfo: IKnowledgeFile;
}> &
  IChunkListResult => {
  const chunkIds = options?.chunkIds?.slice(0, 100);
  const { pagination, setPagination } = useGetPaginationWithRouter();
  const { documentId, knowledgeId } = useGetKnowledgeSearchParams();
  const { searchString, handleInputChange } = useHandleSearchChange();
  const [available, setAvailable] = useState<number | undefined>();
  const debouncedSearchString = useDebounce(searchString, { wait: 500 });

  const {
    data,
    isFetching: loading,
    dataUpdatedAt,
  } = useQuery({
    queryKey: ChunkKeys.list(knowledgeId, documentId, {
      page: pagination.current,
      size: pagination.pageSize,
      keywords: debouncedSearchString,
      available,
      chunkIds,
    }),
    placeholderData: (previousData: any) =>
      previousData ?? { data: [], total: 0, documentInfo: {} }, // https://github.com/TanStack/query/issues/8183
    gcTime: 0,
    enabled: enabled && !!knowledgeId && !!documentId,
    queryFn: async () => {
      const { data } = await kbService.chunkList({
        kb_id: knowledgeId,
        doc_id: documentId,
        page: chunkIds?.length ? 1 : pagination.current,
        size: chunkIds?.length
          ? chunkIds.length
          : Math.min(pagination.pageSize, 100),
        available_int: available,
        keywords: debouncedSearchString,
        chunk_ids: chunkIds,
      });
      if (data.code === 0) {
        const res = data.data;
        return {
          data: res.chunks,
          total: res.total,
          documentInfo: res.doc,
        };
      }

      return (
        data?.data ?? {
          data: [],
          total: 0,
          documentInfo: {},
        }
      );
    },
  });

  const onInputChange: React.ChangeEventHandler<HTMLInputElement> = useCallback(
    (e) => {
      setPagination({ page: 1 });
      handleInputChange(e);
    },
    [handleInputChange, setPagination],
  );

  const handleSetAvailable = useCallback(
    (a: number | undefined) => {
      setPagination({ page: 1 });
      setAvailable(a);
    },
    [setAvailable, setPagination],
  );

  return {
    data,
    loading,
    pagination,
    setPagination,
    searchString,
    handleInputChange: onInputChange,
    available,
    handleSetAvailable,
    dataUpdatedAt, // Timestamp when data was last updated - useful for cache busting
  };
};

/**
 * The same chunk list, read as ONE continuous list instead of pages.
 *
 * A document's passages are a reading order, not a table to be paged: the chunk
 * preview shows them all, in order, and asks the server for the next block only
 * when the reader reaches the end of what is on screen. The request is exactly as
 * narrow as before - keywords, the enabled/disabled filter and the chunk-id filter
 * are the same query parameters - so searching and filtering still reset the list
 * to its first block and re-read it.
 *
 * The first block is fetched immediately (as a page would be) rather than on the
 * first scroll, so the list is never empty for a document that has chunks.
 */
export const useContinuousChunkList = (
  enabled = true,
  options?: { chunkIds?: string[] },
): {
  chunks: IChunk[];
  total: number;
  documentInfo: IKnowledgeFile;
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  loadMore: () => void;
  searchString: string;
  handleInputChange: React.ChangeEventHandler<HTMLInputElement>;
  available: number | undefined;
  handleSetAvailable: (available: number | undefined) => void;
  dataUpdatedAt?: number;
} => {
  // Memoized on the array the caller owns: a fresh array every render would make
  // the query key a fresh object every render.
  const chunkIds = useMemo(
    () => options?.chunkIds?.slice(0, CHUNK_MAX_PAGE_SIZE),
    [options?.chunkIds],
  );
  const { documentId, knowledgeId } = useGetKnowledgeSearchParams();
  const [searchString, setSearchString] = useState('');
  const [available, setAvailable] = useState<number | undefined>();
  const debouncedSearchString = useDebounce(searchString, { wait: 500 });

  // One request per block. A chunk-id filter names the chunks it wants, so it is
  // answered in ONE request of exactly that size.
  const pageSize = chunkIds?.length
    ? Math.min(chunkIds.length, CHUNK_MAX_PAGE_SIZE)
    : CHUNK_PAGE_SIZE;

  const filters = useMemo(
    () => ({
      keywords: debouncedSearchString,
      available,
      chunkIds,
    }),
    [debouncedSearchString, available, chunkIds],
  );

  const {
    data,
    isFetching,
    isFetchingNextPage,
    hasNextPage,
    fetchNextPage,
    dataUpdatedAt,
  } = useInfiniteQuery({
    queryKey: ChunkKeys.list(knowledgeId, documentId, filters),
    enabled: enabled && !!knowledgeId && !!documentId,
    gcTime: 0,
    initialPageParam: 1,
    queryFn: async ({ pageParam }) => {
      const { data } = await kbService.chunkList({
        kb_id: knowledgeId,
        doc_id: documentId,
        page: pageParam,
        size: pageSize,
        available_int: available,
        keywords: debouncedSearchString,
        chunk_ids: chunkIds,
      });
      if (data.code === 0) {
        const res = data.data;
        return {
          data: res.chunks ?? [],
          total: res.total ?? 0,
          // The document's own metadata rides along with the first block; the
          // flattening keeps whichever block reported one.
          documentInfo: (res.doc ?? {}) as IKnowledgeFile,
        };
      }
      // A refused read is an empty block, not an error the list can render: the
      // request layer has already reported it.
      return { data: [], total: 0, documentInfo: {} as IKnowledgeFile };
    },
    // A chunk-id filtered list is one block and has no next page. Otherwise the
    // server's own total decides, counted against what is already loaded.
    getNextPageParam: (lastPage, allPages) => {
      if (chunkIds?.length) return undefined;
      const loaded = (allPages.length - 1) * pageSize + lastPage.data.length;
      return nextChunkPage({
        loaded,
        total: lastPage.total,
        pageCount: allPages.length,
        lastPageLength: lastPage.data.length,
      });
    },
  });

  const { chunks, total, documentInfo } = useMemo(
    () => flattenChunkPages(data?.pages),
    [data?.pages],
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => setSearchString(e.target.value),
    [],
  );

  const handleSetAvailable = useCallback(
    (a: number | undefined) => setAvailable(a),
    [],
  );

  const loadMore = useCallback(() => {
    if (!hasNextPage || isFetchingNextPage) return;
    void fetchNextPage();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  return {
    chunks,
    total,
    documentInfo,
    // The first block is what makes the list exist; a block arriving behind a
    // reader's scroll must not blank it out, so a "load more" is reported
    // separately and never as the list's own loading state.
    loading: isFetching && !isFetchingNextPage,
    loadingMore: isFetchingNextPage,
    hasMore: !!hasNextPage,
    loadMore,
    searchString,
    handleInputChange,
    available,
    handleSetAvailable,
    dataUpdatedAt,
  };
};

export const useSwitchChunk = () => {
  const { t } = useTranslation();
  const { knowledgeId } = useGetKnowledgeSearchParams();
  const queryClient = useQueryClient();
  const {
    data,
    isPending: loading,
    mutateAsync,
  } = useMutation({
    mutationKey: ['switchChunk'],
    mutationFn: async (params: {
      chunk_ids?: string[];
      available_int?: number;
      doc_id: string;
    }) => {
      const { data } = await kbService.switchChunk({
        ...params,
        kb_id: knowledgeId,
      });
      if (data.code === 0) {
        message.success(t('message.modified'));
        // The list is re-read rather than patched in place: a continuous list
        // holds several blocks, and patching only the one on screen would leave
        // the others showing a state the server no longer has.
        queryClient.invalidateQueries({ queryKey: ChunkKeys.all });
      }
      return data?.code;
    },
  });

  return { data, loading, switchChunk: mutateAsync };
};
