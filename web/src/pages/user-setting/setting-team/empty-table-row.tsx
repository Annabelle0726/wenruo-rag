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

import { TableCell, TableRow } from '@/components/ui/table';
import { Users } from 'lucide-react';

/**
 * The no-data row the two team tables share.
 *
 * A table with no rows used to collapse into one bare line of centred text, so
 * an empty team and a broken table looked the same. The placeholder marks the
 * column span with a quiet icon above the muted line instead, and it neither
 * tints nor draws a separator under the pointer, because there is nothing there
 * to point at. Its column span and wording are the table's own, so it is the same
 * row whether the roster is empty or the search matched nothing.
 */
const EmptyTableRow = ({
  colSpan,
  label,
}: {
  colSpan: number;
  label: string;
}) => {
  return (
    <TableRow className="border-0 hover:bg-transparent">
      <TableCell colSpan={colSpan} className="py-12">
        <div className="flex flex-col items-center justify-center gap-2">
          <Users className="size-5 text-content-tertiary" aria-hidden="true" />
          <span className="text-sm text-content-secondary">{label}</span>
        </div>
      </TableCell>
    </TableRow>
  );
};

export default EmptyTableRow;
