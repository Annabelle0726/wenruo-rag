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
import { cn } from '@/lib/utils';
import dayjs from 'dayjs';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { resolveDayWindow } from './usage-format';

/**
 * The windows a reader may ask for.
 *
 * All three are bounded, and even the widest stays inside the server's own
 * 92-day cap (a longer range is REFUSED, not truncated, on the server). Keeping
 * the presets here means no view can build an unbounded historical request.
 */
export const USAGE_RANGE_PRESETS = [7, 31, 92] as const;

export type UsageRangeDays = (typeof USAGE_RANGE_PRESETS)[number];

/**
 * The inclusive `[start_day, end_day]` window for a preset.
 *
 * "Today" is the browser's own calendar day, and the server resolves the stored
 * periods with the workspace's timezone; a day at the boundary can therefore
 * belong to the neighbouring period in the workspace's zone. The range is the
 * reader's request, not an assertion about the workspace's calendar.
 */
export const useUsageDayWindow = (days: UsageRangeDays) =>
  useMemo(
    () => resolveDayWindow(days, dayjs().format('YYYY-MM-DD')),
    [days],
  );

export function UsageRangeFilter({
  value,
  onChange,
}: {
  value: UsageRangeDays;
  onChange: (days: UsageRangeDays) => void;
}) {
  const { t } = useTranslation();
  const labelKeys: Record<UsageRangeDays, string> = {
    7: 'usage.rangeLast7',
    31: 'usage.rangeLast31',
    92: 'usage.rangeLast92',
  };

  return (
    <div
      className="flex items-center gap-1"
      role="group"
      aria-label={t('usage.rangeLabel')}
      data-testid="usage-range-filter"
    >
      {USAGE_RANGE_PRESETS.map((days) => (
        <Button
          key={days}
          variant="ghost"
          size="sm"
          aria-pressed={value === days}
          className={cn(
            'h-7 rounded-[2px] px-2 text-xs',
            value === days && 'ceramic-nav-item-active',
          )}
          onClick={() => onChange(days)}
        >
          {t(labelKeys[days])}
        </Button>
      ))}
    </div>
  );
}
