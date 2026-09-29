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

import { cn } from '@/lib/utils';
import { PropsWithChildren } from 'react';

type CardContainerProps = { className?: string } & PropsWithChildren;

/**
 * The one card grid: every card list in the app renders inside it, so a card on a
 * home section is exactly the size of the same card on its list page.
 *
 * Rows are left to their contents on purpose. The uniform card size comes from the
 * card itself — `HomeCard` is a fixed 112px and the see-all and create tiles match
 * it — rather than from the grid, because sizing rows to the tallest card would
 * stretch every card in the grid as soon as one of them carried an extra line.
 * Cards that want a different size (compilation templates, skills) keep it.
 *
 * Columns follow the space the page gives the grid, not the window: `auto-fill`
 * adds a track whenever another one fits, so a wide window shows more cards per
 * row instead of the same three stretched ones. The 17rem floor is where the
 * shared card still reads — a 32px identity icon, a three-line text column and an
 * optional trailing pill — and at the 1280px `page-gutter` content cap it lands on
 * 4 tracks of ~275-294px, which is the width the skills and MCP grids already
 * render at their own `xl:grid-cols-4 2xl:grid-cols-5`. Below that cap it steps
 * down to 3, then 2, then 1, on the same widths the old `md:`/`lg:` steps did.
 * `min(17rem, 100%)` keeps the floor from pushing a track wider than the container
 * itself, so a very narrow window scrolls rather than overflowing sideways.
 */
export function CardContainer({ children, className }: CardContainerProps) {
  return (
    <div
      // The page-size default is measured off this grid (`useListCapacity`),
      // which is why the contract is a data attribute rather than a class name:
      // it says "this is the grid the page size is derived from", and it survives
      // any future restyling. `data-list-region` marks the box whose height is
      // the region a page of cards has to fit into - a table page marks its own
      // scrolling wrapper the same way, so one measurement serves both layouts.
      data-card-grid=""
      data-list-region=""
      className={cn(
        'grid auto-rows-auto content-start',
        'grid-cols-[repeat(auto-fill,minmax(min(17rem,100%),1fr))]',
        // The row gap is tighter than the column gap: two rows of cards are one
        // rhythm unit, while two descriptions side by side need the wider gutter
        // to stop reading as one line.
        'gap-x-6 gap-y-4',
        // The list pages scroll this grid, and paginating from a full page to a
        // short one removes the scrollbar: reserving its width keeps the columns
        // from jumping sideways between pages.
        'scrollbar-gutter-stable',
        className,
      )}
    >
      {children}
    </div>
  );
}
