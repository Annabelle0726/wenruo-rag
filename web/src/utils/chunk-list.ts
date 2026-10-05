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

/**
 * The chunk list is a CONTINUOUS list: a document's passages are read top to
 * bottom, and a page control in the middle of that reading puts the tenth passage
 * of a paragraph on a different screen from the eleventh for no reason the reader
 * can see. The list therefore grows as the reader scrolls instead of being cut
 * into pages - which is still "incremental loading", because one document's
 * chunks are unbounded in principle: the API caps a single response at 100, and a
 * long PDF is the case where asking for everything at once is what janks.
 *
 * These are the arithmetic of that window, kept pure so the paging decisions can
 * be tested without a server: which chunks are on screen, whether another request
 * is allowed, and which page it asks for.
 */

import { IChunk, IKnowledgeFile } from '@/interfaces/database/dataset';

/** One response of the chunk list endpoint, as the hook shapes it. */
export interface ChunkListPage {
  data: IChunk[];
  total: number;
  documentInfo: IKnowledgeFile;
}

/** Every chunk loaded so far, in document order. */
export interface ChunkWindow {
  chunks: IChunk[];
  total: number;
  documentInfo: IKnowledgeFile;
}

/** How many chunks one request asks for. */
export const CHUNK_PAGE_SIZE = 50;

/** The endpoint's own ceiling (`REST_API_MAX_PAGE_SIZE`): asking for more is refused. */
export const CHUNK_MAX_PAGE_SIZE = 100;

/**
 * The chunks every loaded page holds, in order, with the server's total.
 *
 * A page that failed to load contributes nothing rather than a hole, and `total`
 * comes from the last page that reported one: it is the server's count, never the
 * number of chunks that happen to be on screen.
 */
export function flattenChunkPages(
  pages: ChunkListPage[] | undefined,
): ChunkWindow {
  if (!pages?.length) {
    return { chunks: [], total: 0, documentInfo: {} as IKnowledgeFile };
  }
  const chunks: IChunk[] = [];
  let total = 0;
  let documentInfo = {} as IKnowledgeFile;
  pages.forEach((page) => {
    page?.data?.forEach((chunk) => chunks.push(chunk));
    if (typeof page?.total === 'number') total = page.total;
    if (page?.documentInfo && Object.keys(page.documentInfo).length) {
      documentInfo = page.documentInfo;
    }
  });
  return { chunks, total, documentInfo };
}

/**
 * Which page to request next, or `undefined` when the list is complete.
 *
 * `loaded` is how many chunks are already in hand, `total` the server's count for
 * the same query, `pageCount` how many responses have arrived. Whether to ask
 * again is decided by the server's total rather than by whether the last response
 * looked full - a response that is exactly one page long is not evidence that the
 * list ends there.
 *
 * A page that came back EMPTY stops the sequence even when the total says there is
 * more: the two disagreeing is a reason to stop asking, not to ask in a loop.
 */
export function nextChunkPage({
  loaded,
  total,
  pageCount,
  lastPageLength,
}: {
  loaded: number;
  total: number;
  pageCount: number;
  lastPageLength: number;
}): number | undefined {
  if (!(total > 0) || loaded >= total) return undefined;
  if (lastPageLength === 0) return undefined;
  return pageCount + 1;
}
