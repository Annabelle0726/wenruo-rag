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

import ExpandableContent from '@/components/expandable-content';
import { FileIcon } from '@/components/icon-font';
import { ImageWithPopover } from '@/components/image';
import { Button } from '@/components/ui/button';
import { ITestingChunk } from '@/interfaces/database/dataset';
import { cn } from '@/lib/utils';
import { sanitizeHtmlWithImagesAsText } from '@/utils/dom-util';
import { Crosshair } from 'lucide-react';
import { useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';

/**
 * How much of a passage is shown before it is cut off, in pixels: six lines of
 * the body text. Enough to judge whether the passage answers the question,
 * short enough that five of them stay on one screen.
 */
const DEFAULT_CONTENT_MAX_HEIGHT = 144;

export interface ReferenceSliceCardProps {
  chunk: ITestingChunk;
  /** 1-based position in the result list, shown as the slice number. */
  index: number;
  /** Opens the passage in its document; the card offers it from the header. */
  onLocate?: (documentId: string, chunk: ITestingChunk) => void;
  /** Body height before the fade and the expand control appear. */
  contentMaxHeight?: number;
  className?: string;
}

const formatMetadataValue = (value: unknown) => {
  if (Array.isArray(value)) return value.join(', ');
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
};

/** One line of the header: the same chip in every slot, so the row stays calm. */
const headerChip =
  'inline-flex max-w-full items-center gap-1 rounded border border-border-default bg-bg-base px-1.5 py-0.5 text-xs text-text-secondary';

/**
 * One retrieved passage.
 *
 * Everything in here is expressed with the semantic tokens from
 * `tailwind.css`, which resolve per theme: `bg-bg-card` is white in light mode
 * and #232730 in dark, `border-border-default` is #dcdfe6 and #2f3440. Writing
 * `dark:` twins of every surface would mean two places to keep in step, and the
 * two themes drift the moment one of them is touched.
 *
 * The highlight is the one case that needs a pair of colours rather than a
 * single surface: `--accent-color` is the brand green with a light-mode value
 * (#007a53) and a dark-mode one (#26a67b), and `--accent-color-soft` is the
 * wash behind it. That is the "translucent green behind a green label" the
 * design asks for, on both themes, without hard-coding a palette colour.
 */
export default function ReferenceSliceCard({
  chunk,
  index,
  onLocate,
  contentMaxHeight = DEFAULT_CONTENT_MAX_HEIGHT,
  className,
}: ReferenceSliceCardProps) {
  const { t } = useTranslation();

  const metadata = useMemo(
    () =>
      Object.entries(chunk.document_metadata ?? {}).filter(
        ([, value]) => formatMetadataValue(value) !== '',
      ),
    [chunk.document_metadata],
  );

  const score = useMemo(() => {
    const similarity = Number(chunk.similarity);
    return Number.isFinite(similarity)
      ? `${Math.round(similarity * 100)}%`
      : null;
  }, [chunk.similarity]);

  const content = useMemo(
    () => sanitizeHtmlWithImagesAsText(chunk.highlight || chunk.content).trim(),
    [chunk.content, chunk.highlight],
  );

  const handleLocate = useCallback(() => {
    onLocate?.(chunk.document_id, chunk);
  }, [chunk, onLocate]);

  return (
    <article
      className={cn(
        'flex flex-col overflow-hidden rounded border border-border-default bg-bg-card',
        'transition-colors duration-200',
        // The border firms up under the pointer rather than gaining a shadow:
        // this design system pins every shadow to none and every radius to 2px.
        'hover:border-text-primary/30 hover:bg-surface-hover',
        className,
      )}
      data-testid="reference-slice"
    >
      <header className="flex flex-wrap items-center gap-2 border-b border-border-default px-3 py-2">
        <span
          className="text-xs font-medium text-text-secondary"
          data-testid="reference-slice-index"
        >
          {t('chunk.sliceIndex', { index })}
        </span>

        {chunk.document_keyword && (
          <span className={headerChip}>
            <FileIcon name={chunk.document_keyword} />
            <span className="truncate">{chunk.document_keyword}</span>
          </span>
        )}

        {score && (
          <span className={headerChip} data-testid="reference-slice-score">
            {t('chunk.sliceScore')}
            <span className="font-semibold text-text-primary">{score}</span>
          </span>
        )}

        {onLocate && (
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto gap-1 text-accent-color hover:bg-accent-color-soft hover:text-accent-color-strong"
            onClick={handleLocate}
            data-testid="reference-slice-locate"
          >
            <Crosshair className="size-3.5" />
            {t('chunk.sliceLocate')}
          </Button>
        )}
      </header>

      <div className="flex min-w-0 flex-col px-3 py-3">
        {chunk.image_id && <ImageWithPopover id={chunk.image_id} />}

        {content && (
          <ExpandableContent
            maxHeight={contentMaxHeight}
            fadeFromClassName="from-bg-card"
          >
            <div
              dangerouslySetInnerHTML={{ __html: content }}
              data-testid="reference-slice-content"
              className={cn(
                'text-wrap break-words whitespace-pre text-sm leading-relaxed text-text-primary',
                // The backend wraps every matched term in <em>. Marking them is
                // the point of the passage being here at all, so they get the
                // wash and the ink rather than an underline nobody notices.
                '[&_em]:not-italic [&_em]:rounded [&_em]:px-1 [&_em]:font-semibold',
                '[&_em]:bg-accent-color-soft [&_em]:text-accent-color',
              )}
            />
          </ExpandableContent>
        )}

        {metadata.length > 0 && (
          // The parameters a reader scans for — 特性阻抗, 衰减 — arrive as the
          // passage's metadata. Two columns keep a long list from turning the
          // card into a paragraph.
          <dl
            className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 border-t border-border-default pt-3"
            data-testid="reference-slice-metadata"
          >
            {metadata.map(([key, value]) => (
              <div key={key} className="flex min-w-0 items-baseline gap-1.5">
                <dt className="shrink-0 text-xs text-text-secondary">
                  {key}
                </dt>
                <dd className="min-w-0 truncate text-xs font-medium text-text-primary">
                  {formatMetadataValue(value)}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </article>
  );
}
