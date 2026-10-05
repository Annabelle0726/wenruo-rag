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

import { Button } from '@/components/ui/button';
import ReferenceSliceCard from '@/components/reference-slice-card';
import { ITestingChunk } from '@/interfaces/database/dataset';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

/**
 * How many passages the result page opens with.
 *
 * The retrieval list is evidence for the answer above it, not a corpus dump: a
 * tuned search returns a dozen passages of which the reader checks the first
 * few, and rendering all of them pushed the related-search links and the
 * pagination summary off the first screen. The rest stay one click away, and
 * the count shown on the button says how many that is.
 */
const VISIBLE_SLICE_COUNT = 5;

interface ReferenceSlicesProps {
  chunks: ITestingChunk[];
  onOpenDocument: (documentId: string, chunk: ITestingChunk) => void;
}

export default function ReferenceSlices({
  chunks,
  onOpenDocument,
}: ReferenceSlicesProps) {
  const { t } = useTranslation();
  const [visibleCount, setVisibleCount] = useState(VISIBLE_SLICE_COUNT);

  // A new search brings a new list, so the list collapses back to its opening
  // length instead of keeping the previous query's expansion.
  useEffect(() => {
    setVisibleCount(VISIBLE_SLICE_COUNT);
  }, [chunks]);

  const handleExpand = useCallback(() => {
    setVisibleCount(chunks.length);
  }, [chunks.length]);

  const handleCollapse = useCallback(() => {
    setVisibleCount(VISIBLE_SLICE_COUNT);
  }, []);

  const isExpanded = visibleCount >= chunks.length;

  return (
    <div className="mt-3" data-testid="reference-slices">
      <div className="flex flex-col gap-3">
        {chunks.slice(0, visibleCount).map((chunk, index) => (
          <ReferenceSliceCard
            key={chunk.id ?? index}
            chunk={chunk}
            index={index + 1}
            onLocate={onOpenDocument}
          />
        ))}
      </div>

      {chunks.length > VISIBLE_SLICE_COUNT && (
        <div className="mt-3 flex justify-center">
          <Button
            variant="outline"
            className="gap-1.5"
            onClick={isExpanded ? handleCollapse : handleExpand}
            data-testid="reference-slices-toggle"
          >
            {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            <span>
              {isExpanded
                ? t('search.collapseSlices')
                : t('search.expandSlices', {
                    count: chunks.length - VISIBLE_SLICE_COUNT,
                  })}
            </span>
          </Button>
        </div>
      )}
    </div>
  );
}
