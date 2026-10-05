import { gridCapacity, rowsThatFit } from '@/utils/list-capacity';
import { useLayoutEffect, useSyncExternalStore } from 'react';

/**
 * What a paginated list's own region can show, measured from the region itself.
 *
 * The region is marked `data-list-region` by the page that owns it. When regions
 * are nested — a page shell marks the box the shell gives it, and the list inside
 * marks the tighter box it actually pages by — the INNERMOST one wins: it is the
 * box whose height the list owns, and the outer one also carries page headers and
 * toolbars whose heights are not the list's business.
 *
 * The measurement reads the live box rather than repeating the layout's
 * arithmetic:
 *
 *   columns  - the resolved `grid-template-columns` track count (the `auto-fill`
 *              sizing in `CardContainer` decides how many fit across)
 *   rows     - the region's height divided by a complete item's height + the gap
 *   capacity - columns x rows for a grid, rows for a table
 *
 * TWO AXES, ONE OF WHICH MAY NOT MOVE THE ANSWER. A grid's column count follows
 * the width it is given, so a narrower region really does hold fewer cards. A
 * table's does not: its rows are a fixed height and its cells never wrap (see
 * `DatasetTable`/`FilesTable`), so a table's capacity is a function of the
 * region's HEIGHT alone. That is deliberate. When the row height followed the
 * width — a squeezed cell wrapping to two lines — collapsing the sidebar turned 7
 * rows into 5, and the count was also being read off whatever rows had arrived,
 * which made the page size depend on its own answer.
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
 * The row height a table region states about itself, in `data-list-item-height`.
 *
 * A table declares this because its row pitch is a design contract, not an
 * observation: the list rows are `h-[38px]` with no vertical padding and never
 * wrap, so every row costs the same (`TABLE_ROW_PITCH_PX` - the 38px row plus the
 * separator it draws) whatever the table holds and however wide the region is.
 * Reading the contract is what lets the FIRST request already ask for a whole page
 * - and it is what keeps the page size from being derived from the rows that
 * happen to have arrived.
 */
const declaredItemHeightOf = (region: HTMLElement) => {
  const declared = Number.parseFloat(region.dataset.listItemHeight ?? '');
  return Number.isFinite(declared) && declared > 0 ? declared : 0;
};

/**
 * A row that is NOT data: a skeleton, a spinner, an empty state or an error.
 *
 * These are deliberately a different height from a real row (96px or 120px against
 * a 38px document row), so measuring one pages the table by a third of what it can
 * show - and it does so exactly when the list is empty or refused, which is the
 * reading that then sticks until the data lands.
 */
const isPlaceholderRow = (row: Element) => row.hasAttribute('data-skeleton');

/**
 * How tall one table row is: the height the region declares, raised by a real
 * rendered row when that row is TALLER than the declaration.
 *
 * The declaration stands on its own - a region that states 38px pages by 38px with
 * no data on screen at all. A live row can only raise it, because a row taller than
 * the contract is a layout fact the capacity has to respect; letting it LOWER the
 * reading is what would make the page size follow the page it produced.
 */
const tableRowHeightOf = (region: HTMLElement) => {
  const rows = [...region.querySelectorAll('tbody tr')];
  const row = rows.find((candidate) => !isPlaceholderRow(candidate));
  const measured = row ? row.getBoundingClientRect().height : 0;
  return Math.max(declaredItemHeightOf(region), measured);
};

const isGrid = (style: CSSStyleDeclaration) => style.display === 'grid';

/**
 * The horizontal scrollbar on the table's own scroll box, in px (0 when there is
 * none).
 *
 * The shared `Table` root is the box a wide table scrolls in, and its `clientHeight`
 * already excludes that scrollbar while the REGION's does not. Counting those 10px
 * as row space pages the table by one row it cannot show - which is exactly how a
 * table that fits its height ends up with an internal vertical scrollbar because
 * its WIDTH overflowed. Measured as the difference between the box's border box and
 * its client box, so a border (there is none here) would not be mistaken for one.
 */
const sidewaysScrollbarOf = (
  table: Element | null,
  region: HTMLElement,
): number => {
  const wrapper = table?.parentElement;
  if (!wrapper || wrapper === region) return 0;
  const wrapperBox = wrapper as HTMLElement;
  return Math.max(0, wrapperBox.offsetHeight - wrapperBox.clientHeight);
};

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
    const sideways = sidewaysScrollbarOf(table, region);
    const available =
      region.clientHeight - aboveTable - headerHeight - footerHeight - sideways;
    return rowsThatFit(available, rowHeight);
  })();

  return measured >= MIN_TRUSTWORTHY_CAPACITY ? measured : null;
}

/**
 * The one region on screen, and the one reading of it.
 *
 * Every paginated page mounts several hooks that each need this number - a list
 * query, a search handler, a "go back a page when empty" helper - and when each of
 * them owned its own `ResizeObserver` and `MutationObserver` they all measured the
 * same box, all published their own reading of it, and a resize burst produced
 * several competing answers and several refetches. The measurement lives here
 * instead, shared by every subscriber, so a stable viewport converges on ONE
 * reading no matter how many hooks ask for it.
 */
type Capacity = number | null;

/**
 * The published reading, and whether a region has been read at all yet.
 *
 * `measured` is deliberately not "the capacity is known": a page with no region,
 * or a region too small to trust, has been MEASURED and its answer is "no number".
 * It exists so a caller can tell "the region has not been read yet (this is the
 * first commit, before the layout effect)" apart from "the region was read and
 * reported nothing" - the first is a moment, the second is an answer. A query may
 * wait for a measurement that is guaranteed to have happened, but the switch that
 * decides it is never the arithmetic: it is published by the same layout effect
 * that measures, so it cannot stay closed.
 */
type CapacitySnapshot = { capacity: Capacity; measured: boolean };

let snapshot: CapacitySnapshot = { capacity: null, measured: false };
let observedRegion: HTMLElement | null = null;
let resizeObserver: ResizeObserver | undefined;
let contentObserver: MutationObserver | undefined;
let bodyObserver: MutationObserver | undefined;
/** The previous frame's raw reading, used to confirm one before publishing it. */
let lastReading: Capacity | undefined;
/** False until this region's first reading has been published. */
let confirmed = false;
let frame = 0;

const listeners = new Set<() => void>();

/** The capacity last published, readable outside React (the pager shows it). */
export const currentListCapacity = () => snapshot.capacity;

export const getListCapacitySnapshot = () => snapshot;

/**
 * The innermost marked region, or null when the page has none.
 *
 * `querySelectorAll` returns document order, so the last match is the most deeply
 * nested one - the box whose height the list itself owns.
 */
const findRegion = (): HTMLElement | null => {
  const regions = document.querySelectorAll<HTMLElement>('[data-list-region]');
  return regions.length ? regions[regions.length - 1] : null;
};

const publish = (next: Capacity, measured = true) => {
  if (next === snapshot.capacity && measured === snapshot.measured) return;
  snapshot = { capacity: next, measured };
  listeners.forEach((listener) => listener());
};

/**
 * One reading, and the decision to publish it.
 *
 * A region's FIRST reading is published at once: the caller measures it before the
 * browser paints, so the first request can already be a whole page instead of
 * fetching a default and correcting itself. Every reading after that has to be
 * confirmed by the next frame, because a resize burst (a sidebar transition, a zoom
 * step) produces a different number on every frame and only the number the layout
 * settles on is a page size - this is what turns 7 -> 6 -> 7 -> 5 into one final 5.
 */
const measure = () => {
  const region = observedRegion;
  if (!region) return;
  const next = readRegionCapacity(region);
  // Mirrored onto the region so the number the page is paging by can be read
  // straight off the DOM (devtools, and the browser acceptance checks).
  region.dataset.listCapacity = next === null ? 'unmeasured' : String(next);

  if (!confirmed) {
    confirmed = true;
    lastReading = next;
    publish(next);
    return;
  }
  if (next !== lastReading) {
    lastReading = next;
    schedule();
    return;
  }
  publish(next);
};

const detachRegion = () => {
  resizeObserver?.disconnect();
  contentObserver?.disconnect();
  resizeObserver = undefined;
  contentObserver = undefined;
  observedRegion = null;
  lastReading = undefined;
  confirmed = false;
};

/** Follow the innermost region, whatever the page has mounted this time. */
const syncRegion = () => {
  // `querySelectorAll` only ever returns connected nodes, so a region this page
  // has dropped reads as "something else" (or as nothing) here.
  const next = findRegion();
  if (next === observedRegion) {
    // Still no region: a reading left over from a page that has gone must not
    // become this page's page size. (A reading for a region that is still on
    // screen stays - the page has not changed its mind about it.)
    if (!next) publish(null);
    return;
  }
  detachRegion();
  if (!next) {
    publish(null);
    return;
  }
  observedRegion = next;
  // Both axes: a window resize changes the region's box, and so does a sidebar
  // toggle or a browser zoom step.
  resizeObserver = new ResizeObserver(schedule);
  resizeObserver.observe(next);
  // The region's height is fixed by the shell, so rows and cards arriving inside it
  // do NOT resize it: without this the first page's rows would replace a loading
  // skeleton and leave the capacity unmeasured forever.
  contentObserver = new MutationObserver(schedule);
  contentObserver.observe(next, { childList: true, subtree: true });
  // Published before the paint that mounts this region, when the hook asks for it.
  measure();
};

function tick() {
  frame = 0;
  syncRegion();
  measure();
}

/**
 * Coalesces every trigger - a resize observation, a content mutation, a new
 * region appearing - into ONE reading per frame.
 *
 * A sidebar toggle animates its width over 200ms: without this, that is a dozen
 * readings and a dozen candidate page sizes for a list that only ever needed the
 * last one.
 */
function schedule() {
  if (frame) return;
  frame = requestAnimationFrame(tick);
}

const start = () => {
  // A page renders its region in its own commit, which can be later than this
  // subscription: watch the document for it rather than measuring once and
  // giving up. The watcher is coalesced into the same frame as everything else.
  bodyObserver = new MutationObserver(schedule);
  bodyObserver.observe(document.body, { childList: true, subtree: true });
  tick();
};

const stop = () => {
  bodyObserver?.disconnect();
  bodyObserver = undefined;
  if (frame) {
    cancelAnimationFrame(frame);
    frame = 0;
  }
  detachRegion();
};

export const subscribeListCapacity = (listener: () => void) => {
  listeners.add(listener);
  if (listeners.size === 1) start();
  return () => {
    listeners.delete(listener);
    if (!listeners.size) stop();
  };
};

/**
 * The capacity of the list region on screen, shared by every caller on the page.
 *
 * A page's frame mounts before its data does, so this resolves on the first commit
 * rather than after the first response, and the query that follows it already asks
 * for a number the viewport can hold.
 */
export function useListCapacity(): {
  capacity: Capacity;
  measured: boolean;
} {
  const { capacity, measured } = useSyncExternalStore(
    subscribeListCapacity,
    getListCapacitySnapshot,
    getListCapacitySnapshot,
  );

  useLayoutEffect(() => {
    // `subscribe` runs after paint; measuring here as well is what lets the very
    // first request ask for a whole page.
    //
    // Unconditionally, not only when nothing has been measured yet: this page's
    // region must be measured before this page paints, and the store may still be
    // holding the region of a page that has just been unmounted. That stale reading
    // is a page size the new page would request and then correct - a wasted request
    // and one visible re-layout of the list. `tick` is idempotent: it compares the
    // innermost region with the one it is watching and returns when they match.
    tick();
  }, []);

  return { capacity, measured };
}
