import { useLayoutEffect, useRef, useState } from 'react';
import { gridCapacity, rowsThatFit } from '@/utils/list-capacity';

/**
 * What a paginated list's own region can show, measured from the region itself.
 *
 * The region is marked `data-list-region` by the page that owns it: a card grid
 * on the card pages, the scrolling wrapper of a table on the table pages. The
 * measurement reads the live box rather than repeating the layout's arithmetic,
 * so a sidebar toggle, a zoom step, a changed toolbar or a different theme are
 * all handled by measuring again:
 *
 *   columns  - the resolved `grid-template-columns` track count (the `auto-fill`
 *              sizing in `CardContainer` decides how many fit across)
 *   rows     - the region's height divided by a complete item's height + the gap
 *   capacity - columns x rows for a grid, rows for a table
 *
 * The item height comes from a rendered item when there is one. Before any data
 * has arrived there is nothing to measure, so a grid falls back to
 * `--list-card-height` - the same token `HomeCard` builds its row from - which is
 * what lets the FIRST request already ask for the right number of records instead
 * of fetching 50 to find out.
 */

/** A card row, a see-all tile and a create tile are all this tall. */
const MIN_ITEM_HEIGHT = 40;

const ITEM_HEIGHT_TOKEN = '--list-card-height';

/**
 * Below this, a measurement is a mis-measurement rather than a design.
 *
 * A region measured mid-layout, or one holding nothing but a loading skeleton,
 * can read as one or two items tall - and a page size of 2 is not "what the
 * viewport can show", it is a page that has not finished laying out. The shell
 * gives every list region hundreds of pixels, so a capacity under five means the
 * region is not ready to be measured, not that the page should page by two.
 */
export const MIN_TRUSTWORTHY_CAPACITY = 5;

const itemHeightOf = (region: HTMLElement, style: CSSStyleDeclaration) => {
  const rendered = [...region.children].find(
    (child) => child.getBoundingClientRect().height >= MIN_ITEM_HEIGHT,
  );
  if (rendered) return rendered.getBoundingClientRect().height;
  const token = Number.parseFloat(style.getPropertyValue(ITEM_HEIGHT_TOKEN));
  return Number.isFinite(token) && token > 0 ? token : 0;
};

/**
 * The first REAL row of a table body: the unit a table page pages by.
 *
 * A loading skeleton is a deliberately different height (`h-24` against a 38px
 * row), so measuring one would page the table by the wrong number until the data
 * landed. Skeleton rows are skipped. Before any row has rendered, the region may
 * declare `data-list-item-height` - the table's own row height, stated once next
 * to the table that uses it - so the first request can still be a whole page.
 */
const tableRowHeightOf = (region: HTMLElement) => {
  const rows = [...region.querySelectorAll('tbody tr')];
  const row = rows.find((candidate) => !candidate.hasAttribute('data-skeleton'));
  if (row) return row.getBoundingClientRect().height;
  const declared = Number.parseFloat(region.dataset.listItemHeight ?? '');
  return Number.isFinite(declared) && declared > 0 ? declared : 0;
};

const isGrid = (style: CSSStyleDeclaration) => style.display === 'grid';

/**
 * How many complete items `region` can show, or `null` when it cannot be
 * measured yet (no region, no item height to page by, or a reading too small to
 * be a real region).
 *
 * The region may hold more than the list: a page's frame carries its own toolbar
 * above the table, and its pagination can live inside the same box. What the
 * table sits below, its header, and a `data-list-footer` are subtracted - the
 * capacity is the space the ROWS have, not the space the box has.
 */
export function readRegionCapacity(region: HTMLElement | null): number | null {
  if (!region) return null;
  const style = window.getComputedStyle(region);

  const measured = (() => {
    if (isGrid(style)) {
      const columns = style.gridTemplateColumns
        .split(' ')
        .filter((track) => track && track !== 'none').length;
      const itemHeight = itemHeightOf(region, style);
      const rowGap = Number.parseFloat(style.rowGap) || 0;
      const rows = rowsThatFit(region.clientHeight, itemHeight, rowGap);
      return gridCapacity(columns, rows);
    }

    const rowHeight = tableRowHeightOf(region);
    if (!rowHeight) return 0;
    const table = region.querySelector('table');
    const header = region.querySelector('thead');
    const footer = region.querySelector('[data-list-footer]');
    const regionBox = region.getBoundingClientRect();
    // Space above the table inside the same region: a card header, a toolbar.
    const aboveTable = table
      ? table.getBoundingClientRect().top - regionBox.top + region.scrollTop
      : 0;
    const headerHeight = header ? header.getBoundingClientRect().height : 0;
    const footerHeight = footer ? footer.getBoundingClientRect().height : 0;
    const available =
      region.clientHeight - aboveTable - headerHeight - footerHeight;
    return rowsThatFit(available, rowHeight);
  })();

  return measured >= MIN_TRUSTWORTHY_CAPACITY ? measured : null;
}

/**
 * The last measured capacity, readable outside React.
 *
 * The pager shows the size the page is actually using, so it has to know the same
 * capacity - and making every call site pass it would leave one forgotten site
 * displaying a size the page is not using. The measured value is published here
 * and the pager reads it; a page that re-renders on a capacity change re-renders
 * its pager with the new value.
 */
let publishedCapacity: number | null = null;

export const currentListCapacity = () => publishedCapacity;

/**
 * The capacity of the list region on screen, re-measured whenever that region
 * changes size.
 *
 * `ready` is false until a capacity is known, and pages hold their list query
 * until it is true: that is what keeps the first request from asking for a
 * number the viewport cannot show. The region is mounted by the page's own frame
 * (not by its data), so this resolves on the first commit rather than after the
 * first response.
 */
export function useListCapacity(): {
  capacity: number | null;
  ready: boolean;
} {
  const [capacity, setCapacity] = useState<number | null>(null);
  // A page whose list has no marked region (a table on a settings page, say) must
  // not wait forever for a measurement that will never come: after a grace period
  // the query is released with the cap, which is what such a page did before
  // capacities existed.
  const [gaveUp, setGaveUp] = useState(false);
  // A region read while the page is still laying out reports a height the page
  // will not keep - a header that has not taken its space yet, a table whose first
  // real row has not replaced its skeleton. Publishing such a reading pages the
  // list by the wrong number and refetches when the layout settles, so a value is
  // only published once the next frame agrees with it.
  const pendingCapacity = useRef<number | null | undefined>(undefined);

  useLayoutEffect(() => {
    let resizeObserver: ResizeObserver | undefined;
    let contentObserver: MutationObserver | undefined;
    let measuredRegion: HTMLElement | null = null;

    const measure = () => {
      const next = readRegionCapacity(measuredRegion);
      // Mirrored onto the region so the number the page is paging by can be read
      // straight off the DOM (devtools, and the browser acceptance checks).
      if (measuredRegion) {
        measuredRegion.dataset.listCapacity =
          next === null ? 'unmeasured' : String(next);
      }
      if (pendingCapacity.current !== next) {
        // First sighting of this value: remember it, confirm on the next frame.
        pendingCapacity.current = next;
        requestAnimationFrame(() => measure());
        return;
      }
      publishedCapacity = next;
      setCapacity((previous) => (previous === next ? previous : next));
    };

    const attach = () => {
      const region = document.querySelector<HTMLElement>('[data-list-region]');
      if (!region) return false;
      measuredRegion = region;
      // A layout effect runs before the browser paints, so the first request
      // already has a capacity when the region is part of the first render.
      measure();
      // Both axes: a window resize changes the region's box, and so does a
      // sidebar toggle or a browser zoom step.
      resizeObserver = new ResizeObserver(measure);
      resizeObserver.observe(region);
      // The region's height is fixed by the shell, so rows and cards arriving
      // inside it do NOT resize it: without this the first page's rows would
      // replace a loading skeleton and leave the capacity unmeasured forever.
      contentObserver = new MutationObserver(measure);
      contentObserver.observe(region, { childList: true, subtree: true });
      return true;
    };

    if (attach()) {
      return () => {
        resizeObserver?.disconnect();
        contentObserver?.disconnect();
      };
    }

    // The region belongs to the page's frame; watch for it rather than measuring
    // once and giving up, so a page that renders its frame late still pages by
    // its real capacity. If it never appears, the grace period releases the query.
    const graceTimer = setTimeout(() => setGaveUp(true), 400);
    const mutations = new MutationObserver(() => {
      if (attach()) mutations.disconnect();
    });
    mutations.observe(document.body, { childList: true, subtree: true });

    return () => {
      clearTimeout(graceTimer);
      mutations.disconnect();
      resizeObserver?.disconnect();
      contentObserver?.disconnect();
    };
  }, []);

  return { capacity, ready: capacity !== null || gaveUp };
}
