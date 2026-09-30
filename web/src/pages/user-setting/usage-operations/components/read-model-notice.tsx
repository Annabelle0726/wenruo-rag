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
import { LucideCircleDashed } from 'lucide-react';
import { useTranslation } from 'react-i18next';

/**
 * The surface that owns a usage read's failure.
 *
 * The usage reads deliberately keep their errors OUT of the global toast: one
 * transient toast per endpoint per retry is the wrong shape for a page that has
 * seven of them, and it tells a reader nothing about the figures they are
 * looking at. This panel says which read failed, why it can fail, and offers an
 * explicit retry - so the failure is more visible than a toast, not less.
 *
 * Nothing here replaces a missing figure with a number: the numbers stay absent.
 */
export function ReadModelNotice({
  failed,
  onRetry,
  testId,
}: {
  failed: boolean;
  onRetry: () => void;
  testId?: string;
}) {
  const { t } = useTranslation();

  return (
    <div className="settings-notice" data-testid={testId}>
      <LucideCircleDashed className="mt-0.5 size-4 shrink-0 text-text-disabled" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="settings-notice-title">
          {t(
            failed
              ? 'usage.readModelUnavailableTitle'
              : 'usage.readModelEmptyTitle',
          )}
        </p>
        <p className="settings-notice-body">
          {t(
            failed
              ? 'usage.readModelUnavailableDescription'
              : 'usage.readModelEmptyDescription',
          )}
        </p>

        {failed && (
          <div className="pt-1">
            <Button
              variant="outline"
              size="sm"
              className="h-8 px-3 text-xs"
              onClick={onRetry}
            >
              {t('common.retry')}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

export default ReadModelNotice;
