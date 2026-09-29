import { useEffect, useState } from 'react';

/** The page sizes `RAGFlowPagination` offers, ascending. */
export const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;

/** A card, a see-all tile and a create tile are all this tall. */
const CARD_MIN_HEIGHT = 40;

/**
 * How many cards a page should ask for, so that one page fits the screen.
 *
 * The list pages defaulted to 50 records, which no card area can hold: at
 * 1366x657 (a 1366x768 laptop) the shared grid has ~446px of height, and the
 * 112px card with a 16px row gap fits three rows of four - twelve cards. Fifty
 * cards meant thirteen rows and a scrollbar on every visit, for a list whose
 * whole first page would have been on screen. The count is therefore derived
 * from the grid the page actually rendered rather than from a constant:
 *
 *   - columns come from the grid's resolved `grid-template-columns`, so the
 *     `auto-fill` track sizing in `CardContainer` is the single source of truth
 *     for how many fit across;
 *   - rows come from the grid's own height, the height of a real card and the
 *     grid's row gap, so a row is never cut by the fold;
 *   - the result is snapped to one of the page sizes the pager offers, because
 *     `RAGFlowPagination`'s size control can only display a value it has an
 *     option for.
 *
 * The user's own choice always wins: both the `size` URL parameter and the
 * per-path remembered size are read before this default (see
 * `useSetPaginationParams`), so picking 100 is still possible - it just means
 * scrolling, which is then the user's own call.
 */

/**
 * How many cards the grid could hold: columns across times rows down.
 *
 * Returns `null` when there is nothing to measure - an empty list, or a grid
 * that has not been laid out yet - because a guess would be worse than the
 * caller's own default.
 */
export function readCardGridCapacity(grid: HTMLElement | null): number | null {
  if (!grid) return null;

  const style = window.getComputedStyle(grid);
  const columns = style.gridTemplateColumns
    .split(' ')
    .filter((track) => track && track !== 'none').length;
  if (!columns) return null;

  const card = [...grid.children].find(
    (child) => child.getBoundingClientRect().height >= CARD_MIN_HEIGHT,
  );
  const cardHeight = card?.getBoundingClientRect().height ?? 0;
  if (!cardHeight) return null;

  const rowGap = Number.parseFloat(style.rowGap) || 0;
  const rows = Math.max(
    1,
    Math.floor((grid.clientHeight + rowGap) / (cardHeight + rowGap)),
  );

  return columns * rows;
}

/**
 * The largest offered page size that fits `capacity` cards.
 *
 * Every offered size is a whole number of rows only by accident, so this picks
 * the largest option the area can hold and never invents a size the pager cannot
 * display. Below the smallest option the smallest is still returned: a page that
 * overflows its area is better than one that shows almost nothing.
 */
export function fittedPageSize(
  capacity: number | null,
  options: readonly number[] = PAGE_SIZE_OPTIONS,
): number | undefined {
  if (!capacity || capacity <= 0) return undefined;
  const fits = options.filter((option) => option <= capacity);
  if (!fits.length) return Math.min(...options);
  return Math.max(...fits);
}

/**
 * The last measured capacity, kept across list pages for the life of the tab.
 *
 * A page renders its grid only once its first response arrives, so the very
 * first render of a session has nothing to measure and asks for the fallback
 * count; remembering the answer means the second list page opened in that tab
 * asks for the right count straight away, instead of one throwaway request per
 * navigation. It is a starting point only - the observer corrects it as soon as
 * the real grid is on screen.
 */
let lastCapacity: number | null = null;

/**
 * The fitted page size for the card grid on screen, or `undefined` while there
 * is nothing to measure. Re-measured whenever the grid changes size, so a
 * resized window asks for a count that fits the new area.
 */
export function useFittingPageSize(): number | undefined {
  const [capacity, setCapacity] = useState<number | null>(lastCapacity);

  useEffect(() => {
    let resizeObserver: ResizeObserver | undefined;

    // Returns false when the grid is not in the document yet.
    const attach = () => {
      const grid = document.querySelector<HTMLElement>('[data-card-grid]');
      if (!grid) return false;

      const measure = () => {
        const next = readCardGridCapacity(grid);
        lastCapacity = next;
        // The grid keeps `scrollbar-gutter: stable`, so this cannot oscillate:
        // the measurement does not depend on whether the bar is showing.
        setCapacity((previous) => (previous === next ? previous : next));
      };

      measure();
      // The observer covers both axes: a window resize changes the grid's box,
      // and so does a sidebar toggle or a browser zoom step.
      resizeObserver = new ResizeObserver(measure);
      resizeObserver.observe(grid);
      return true;
    };

    if (attach()) return () => resizeObserver?.disconnect();

    // The grid arrives with the page's first page of data, which is after this
    // effect has run. Watch for it rather than measuring once and giving up -
    // that is the difference between a fitted page size and none at all.
    const mutations = new MutationObserver(() => {
      if (attach()) mutations.disconnect();
    });
    mutations.observe(document.body, { childList: true, subtree: true });

    return () => {
      mutations.disconnect();
      resizeObserver?.disconnect();
    };
  }, []);

  return fittedPageSize(capacity);
}
