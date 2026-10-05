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
import { TagFilterButtonProps } from '../interface';

/** Tag pill used in the filter row. */
export function TagFilterButton({
  label,
  count,
  active,
  onClick,
}: TagFilterButtonProps) {
  return (
    <button
      type="button"
      aria-pressed={active}
      className={cn(
        // One tag shape for the whole settings module: idle is the quiet hairline
        // tag, the selected filter is the brand's soft tint. A solid brand fill
        // here competed with the primary action beside it.
        'settings-tag gap-1 px-2 transition-colors',
        active
          ? 'border-accent-color-soft bg-accent-primary-5 font-medium text-accent-primary'
          : 'text-content-secondary hover:border-accent-color-soft hover:bg-accent-primary-5 hover:text-content-primary',
      )}
      onClick={onClick}
    >
      {label}
      <span className="tabular-nums opacity-60">{count}</span>
    </button>
  );
}
