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

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { Pencil } from 'lucide-react';
import { mapModelKey } from '../../available-models';
import { ModelTypeBadgesProps } from '../interface';

/** Max model-type badges shown inline; the rest collapse into a tooltip. */
const MAX_VISIBLE_TYPES = 3;

/** Renders the model-type badges row, collapsing overflow into a tooltip. */
export function ModelTypeBadges({
  types,
  onEdit,
  showEdit,
  editLabel,
  editTestSuffix,
}: ModelTypeBadgesProps) {
  const visible = types.slice(0, MAX_VISIBLE_TYPES);
  const hidden = types.slice(MAX_VISIBLE_TYPES);
  return (
    <>
      {visible.map((mt) => (
        <span
          key={mt}
          className="settings-tag text-content-secondary"
        >
          {mapModelKey[mt as keyof typeof mapModelKey] || mt}
        </span>
      ))}
      {hidden.length > 0 && (
        <Tooltip>
          <TooltipTrigger asChild>
            <span
              className="settings-tag cursor-default text-content-secondary"
              data-testid={`models-types-overflow-${editTestSuffix}`}
            >
              +{hidden.length}
            </span>
          </TooltipTrigger>
          <TooltipContent>
            <div className="flex flex-wrap gap-1 max-w-[16rem]">
              {hidden.map((mt) => (
                <span
                  key={mt}
                  className="settings-tag text-content-secondary"
                >
                  {mapModelKey[mt as keyof typeof mapModelKey] || mt}
                </span>
              ))}
            </div>
          </TooltipContent>
        </Tooltip>
      )}
      {showEdit && (
        <button
          type="button"
          className="ml-0.5 flex size-5 items-center justify-center rounded-[2px] text-content-tertiary opacity-0 transition-all hover:bg-accent-color-soft hover:text-accent-color group-hover:opacity-100 focus-visible:opacity-100"
          onClick={(e) => {
            e.stopPropagation();
            onEdit?.();
          }}
          aria-label={editLabel}
          title={editLabel}
          data-testid={`models-edit-${editTestSuffix}`}
        >
          <Pencil className="size-3" />
        </button>
      )}
    </>
  );
}
