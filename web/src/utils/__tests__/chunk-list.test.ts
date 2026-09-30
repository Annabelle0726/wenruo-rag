import { describe, expect, it } from '@jest/globals';
import {
  CHUNK_PAGE_SIZE,
  ChunkListPage,
  flattenChunkPages,
  nextChunkPage,
} from '@/utils/chunk-list';

/**
 * The arithmetic of the continuous chunk list: what is on screen, and whether
 * another block may be requested.
 *
 * The list is read in document order with no page control, so the two things that
 * can go wrong are silent: a block dropped between responses (a hole in the
 * reading) and a request loop that never stops adding blocks.
 */
const chunk = (id: string) => ({ chunk_id: id });

const page = (count: number, total: number, offset = 0): ChunkListPage =>
  ({
    data: Array.from({ length: count }, (_, index) =>
      chunk(`chunk-${offset + index}`),
    ),
    total,
    documentInfo: { name: 'doc.pdf' },
  }) as unknown as ChunkListPage;

describe('flattenChunkPages', () => {
  it('keeps every loaded chunk in order', () => {
    const first = page(2, 4);
    const second = page(2, 4, 2);

    const { chunks, total, documentInfo } = flattenChunkPages([first, second]);

    expect(chunks.map((item) => item.chunk_id)).toEqual([
      'chunk-0',
      'chunk-1',
      'chunk-2',
      'chunk-3',
    ]);
    expect(total).toBe(4);
    expect(documentInfo.name).toBe('doc.pdf');
  });

  it('reports nothing at all before the first block arrives', () => {
    // Not "an empty document": a list that has not been read has no count to
    // report, which is why `total` is 0 rather than the chunks on screen.
    expect(flattenChunkPages(undefined)).toEqual({
      chunks: [],
      total: 0,
      documentInfo: {},
    });
    expect(flattenChunkPages([]).chunks).toEqual([]);
  });

  it('lets a later block carry the count and the document', () => {
    const empty = {
      data: [chunk('a')],
      total: 0,
      documentInfo: {},
    } as unknown as ChunkListPage;

    const { total, documentInfo } = flattenChunkPages([empty, page(1, 69)]);

    expect(total).toBe(69);
    expect(documentInfo.name).toBe('doc.pdf');
  });
});

describe('nextChunkPage', () => {
  const ask = (loaded: number, total: number, pageCount: number) =>
    nextChunkPage({
      loaded,
      total,
      pageCount,
      lastPageLength: Math.min(loaded, CHUNK_PAGE_SIZE),
    });

  it('asks for the next block while the server count says there is more', () => {
    expect(ask(CHUNK_PAGE_SIZE, 69, 1)).toBe(2);
    expect(ask(CHUNK_PAGE_SIZE * 2, 69, 2)).toBeUndefined();
  });

  it('stops when everything the server counted is loaded', () => {
    // A whole document under one block: nothing further to ask for, even though
    // the response is exactly one page long.
    expect(ask(30, 30, 1)).toBeUndefined();
    expect(ask(50, 50, 1)).toBeUndefined();
  });

  it('stops instead of looping when a block comes back empty', () => {
    // The server's total and the response disagree; asking again would ask
    // forever, so the sequence ends on the first empty block.
    expect(
      nextChunkPage({
        loaded: 50,
        total: 69,
        pageCount: 1,
        lastPageLength: 0,
      }),
    ).toBeUndefined();
  });

  it('has nothing to ask for before the server has counted anything', () => {
    expect(ask(0, 0, 0)).toBeUndefined();
  });
});
