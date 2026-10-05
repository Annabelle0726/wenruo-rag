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

import { PropsWithChildren } from 'react';

type ProfileSettingWrapperCardProps = {
  header: React.ReactNode;
} & PropsWithChildren;

/**
 * The right-hand settings panel.
 *
 * It is deliberately not a card: no radius and no gutter of its own, it takes
 * the whole height of the settings column and reaches the right and bottom
 * edges of the viewport, so it reads as the page's content area rather than a
 * tile floating on top of it. The surface and the seam keep it separate from
 * the rail beside it; the rail draws the edge.
 *
 * The header is the ONE page header every settings destination shares: same
 * height, same 20px gutter as the body below it (`.settings-body`), and a single
 * hairline between them — so switching destinations does not move the title, the
 * description or the first row of content.
 */
export function ProfileSettingWrapperCard({
  header,
  children,
}: ProfileSettingWrapperCardProps) {
  return (
    <article className="glass-surface relative flex h-full min-h-0 w-full flex-col">
      <header className="flex shrink-0 items-center border-b border-cable-hairline px-5 py-4">
        {header}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto scrollbar-auto">
        {children}
      </div>
    </article>
  );
}
