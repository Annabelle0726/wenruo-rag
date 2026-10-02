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

import { CardSkeleton } from '@/components/ui/skeleton';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useId, useState } from 'react';
import { ReadModelNotice } from './read-model-notice';

/**
 * One block of a usage surface, so every block states its own three states the
 * same way: loading, a failure that the block owns, or content.
 *
 * `collapsible` adds a control to the header and starts the block open or closed.
 * The state is LOCAL and the closed state never removes a figure from the read
 * model - a closed block simply is not rendered until it is opened, which is why
 * `defaultOpen={false}` is only ever used for a block whose figures are secondary.
 */
export function AnalyticsSection({
  title,
  hint,
  loading,
  failed,
  onRetry,
  empty,
  testId,
  children,
  collapsible = false,
  defaultOpen = true,
}: {
  title: string;
  hint?: string;
  loading: boolean;
  failed: boolean;
  onRetry: () => void;
  empty: boolean;
  testId: string;
  children: React.ReactNode;
  collapsible?: boolean;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const expanded = !collapsible || open;
  const bodyId = useId();
  const toggleOpen = () => setOpen((value) => !value);

  return (
    <section className="settings-section">
      <div className="settings-section-head">
        <div className="flex min-w-0 flex-1 items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="settings-section-title">{title}</h3>
            {hint && <p className="settings-section-hint">{hint}</p>}
          </div>
          {collapsible && (
            <button
              type="button"
              className="settings-control inline-flex size-8 shrink-0 items-center justify-center text-lg leading-none text-text-secondary transition-colors hover:text-text-primary"
              aria-expanded={expanded}
              aria-label={title}
              aria-controls={bodyId}
              onClick={toggleOpen}
            >
              {expanded ? (
                <ChevronDown size={16} aria-hidden="true" />
              ) : (
                <ChevronRight size={16} aria-hidden="true" />
              )}
            </button>
          )}
        </div>
      </div>
      {expanded && (
        <div id={bodyId} className="settings-section-body">
          {loading ? (
            <CardSkeleton />
          ) : failed || empty ? (
            <ReadModelNotice failed={failed} onRetry={onRetry} testId={testId} />
          ) : (
            children
          )}
        </div>
      )}
    </section>
  );
}

export default AnalyticsSection;
