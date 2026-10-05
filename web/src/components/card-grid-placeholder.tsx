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
 * Card-sized placeholders for a list that has not arrived yet.
 *
 * A card list renders its grid region before its data, because the page size is
 * the number of complete cards that region holds: `useListCapacity` measures the
 * region and the row height to decide what to ask the API for, and it can only do
 * that once the region exists. These shells provide the row height (the shared
 * `--list-card-height`, the same token the real card uses) without pretending to
 * be data, and they are what the user sees in place of a bare spinner - a page
 * that is about to fill with cards, rather than one that is empty.
 */
const PLACEHOLDER_COUNT = 4;

export function CardGridPlaceholder({
  count = PLACEHOLDER_COUNT,
}: {
  count?: number;
}) {
  return (
    <>
      {Array.from({ length: count }).map((_, index) => (
        <div
          key={index}
          aria-hidden="true"
          data-testid="card-grid-placeholder"
          className="h-[var(--list-card-height)] w-full rounded-xl border border-cable-hairline bg-glass animate-pulse"
        />
      ))}
    </>
  );
}

export default CardGridPlaceholder;
