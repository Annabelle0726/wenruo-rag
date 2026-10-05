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

import { IDataset } from '@/interfaces/database/dataset';

/**
 * Apply personal visibility and pinning to accessible datasets, before pagination.
 * Within each group use the latest update first. A hidden row cannot be pinned.
 *
 * Hiding is a per-user preference, never an authorization decision: the rows the
 * server sends are already the ones this user may read, so dropping one here
 * changes nothing but this view.
 */
export const arrangeDatasets = ({
  datasets,
  pinnedIds,
  hiddenIds,
  showHidden,
}: {
  datasets: IDataset[];
  pinnedIds: string[];
  hiddenIds: string[];
  showHidden: boolean;
}): IDataset[] => {
  const pinned = new Set(pinnedIds);
  const hidden = new Set(hiddenIds);
  const visible = showHidden
    ? datasets
    : datasets.filter((dataset) => !hidden.has(dataset.id));

  return [...visible].sort((a, b) => {
    const pinOrder =
      Number(pinned.has(b.id) && !hidden.has(b.id)) -
      Number(pinned.has(a.id) && !hidden.has(a.id));
    return pinOrder || (b.update_time ?? 0) - (a.update_time ?? 0);
  });
};
