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
 * How many records a paginated list page may ask for.
 *
 * `50` is a CAP, not a default. The size a page requests is the number of
 * COMPLETE items its own viewport region can show, bounded by the user's own
 * choice and by the application cap:
 *
 *   effective = min(viewport capacity, user cap, MAX_PAGE_SIZE)
 *
 * The point of pagination on these pages is that the list never becomes its own
 * long scroll region: with 13 records and room for 12, page 1 shows 12 and page 2
 * shows the last one. Before this, 50 was requested whenever nothing had been
 * chosen, so a 13-record list rendered 13 cards in a region that could show 12
 * and the grid carried a scrollbar that existed only because the page size was
 * wrong.
 */

/** The application's upper bound on a page size. */
export const MAX_PAGE_SIZE = 50;

/** The sizes the pager offers out of the box, ascending. */
export const PAGE_SIZE_PRESETS = [10, 20, 50, 100] as const;

/**
 * The pitch of one row in the app's table lists, which is what a page of rows
 * costs and what a list region declares in `data-list-item-height`.
 *
 * A list row is `h-[38px]` and draws its own `border-b` separator, so the row's
 * border box measures 39px - and 39 is the number the capacity has to divide by.
 * It has to be EXACT, not a round number: a region that declares 38 pages by
 * `floor(available / 38)`, which is one row more than `floor(available / 39)`, so
 * the first request would ask for a row that does not fit and immediately refetch
 * with the measured 39 - which is the jump this declaration exists to avoid.
 *
 * Changing a list row's height or its border means changing this number with it.
 */
export const TABLE_ROW_PITCH_PX = 39;

/**
 * The height of a paginated list's pager row: the pager's own 42px control row
 * plus the 16px gap above it.
 *
 * A list renders its pager only once the read has answered, because a pager states
 * a count and there is no count to state while the read is in flight, refused or
 * failed. The ROW is nevertheless reserved from the first paint: the page size is
 * measured from the space the rows have, and a region measured without a pager
 * reads one row taller than the same region with one - so the size changed the
 * moment the data landed, the table reloaded itself around the new size, and the
 * pager appearing flipped it back. Measured on the live list before this: four
 * document requests on first load (`page_size` 50, 16, 15, 16), four skeleton-and-
 * rows flashes and six column-width layout shifts.
 *
 * Keep it in step with `RAGFlowPagination`'s control row (32px page links and a
 * 32px size trigger inside a `p-1` capsule, i.e. 42px) and the `pt-4` the footer
 * carries above it.
 */
export const PAGER_ROW_HEIGHT_PX = 58;

/**
 * Complete rows of `itemHeight` that fit in `available` px, given `gap` between
 * rows. A partial row never counts: the pagination has to be able to show a whole
 * row, so a row that would be cut by the region's edge belongs to the next page.
 */
export function rowsThatFit(
  available: number,
  itemHeight: number,
  gap = 0,
): number {
  if (!(available > 0) || !(itemHeight > 0)) return 0;
  return Math.max(0, Math.floor((available + gap) / (itemHeight + gap)));
}

/** Items a grid of `columns` shows in `rows`. */
export function gridCapacity(columns: number, rows: number): number {
  if (!(columns > 0) || !(rows > 0)) return 0;
  return columns * rows;
}

/**
 * The page size a page actually uses.
 *
 * `capacity` is what the viewport can show (`null` before anything is measured).
 * `userCap` is the user's own selection, which is a MAXIMUM and not a mandate:
 * asking for 50 records in a region that shows 12 complete cards must still
 * render 12. `max` is the application cap.
 *
 * When the capacity is unknown the user's cap still applies, so nothing requests
 * more than the user allowed while the first measurement is pending.
 */
export function effectivePageSize({
  capacity,
  userCap,
  max = MAX_PAGE_SIZE,
}: {
  capacity?: number | null;
  userCap?: number | null;
  max?: number;
}): number {
  const allowed = Math.max(
    1,
    Math.min(
      max,
      Number.isFinite(userCap) && (userCap as number) > 0
        ? (userCap as number)
        : max,
    ),
  );
  if (!capacity || capacity <= 0) return allowed;
  return Math.max(1, Math.min(capacity, allowed));
}

/**
 * The sizes the size control may offer: the presets that fit this viewport, plus
 * the capacity itself. Nothing above the capacity is offered, because selecting
 * it could not be honoured - and the capacity has to be in the list so the
 * control can display the size the page is really using.
 */
export function pageSizeOptionsFor(capacity?: number | null): number[] {
  if (!capacity || capacity <= 0) return [...PAGE_SIZE_PRESETS];
  const fits = PAGE_SIZE_PRESETS.filter((preset) => preset <= capacity);
  const capped = Math.min(capacity, MAX_PAGE_SIZE);
  return [...new Set([...fits, capped])].sort((a, b) => a - b);
}

/**
 * Which page still shows the record the current page started at, after the page
 * size changed under a resize.
 *
 * Keeping the page NUMBER would silently change the record window (page 3 of 20
 * is offset 40; page 3 of 12 is offset 24, so records would jump backwards). The
 * first visible record is preserved instead, rounded down to the page that
 * contains it.
 */
export function pageAfterResize({
  page,
  fromSize,
  toSize,
}: {
  page: number;
  fromSize?: number | null;
  toSize: number;
}): number {
  if (!(page > 1) || !fromSize || fromSize <= 0 || !(toSize > 0)) return 1;
  if (fromSize === toSize) return page;
  const offset = (page - 1) * fromSize;
  return Math.floor(offset / toSize) + 1;
}
