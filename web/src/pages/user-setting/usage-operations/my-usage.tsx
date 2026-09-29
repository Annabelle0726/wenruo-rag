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
import {
  useFetchMyUsage,
  useFetchQuotaStatus,
} from '@/hooks/use-workspace-usage-request';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ComingDataPanel } from './components/coming-data-panel';
import { LimitStandingList } from './components/limit-standing-list';
import { EstimatedCostTile, UsageTotalsGrid } from './components/usage-metric';
import {
  UsageRangeDays,
  UsageRangeFilter,
  useUsageDayWindow,
} from './components/usage-range-filter';

/**
 * My Usage: the caller's OWN metered usage and current quota standing.
 *
 * It is the one view every member may read, and its subject is the reader rather
 * than the workspace - the server forces that, so this view cannot be pointed at
 * another member's rows even if it tried.
 *
 * There is deliberately NO per-day chart here. A member's own daily series does
 * not exist in the read model: `daily_series` is a workspace-aggregate view the
 * server refuses to a NORMAL caller, and inventing a chart from the window total
 * would draw a trend the records do not support.
 */
function MyUsage() {
  const { t } = useTranslation();
  const [days, setDays] = useState<UsageRangeDays>(31);
  const window = useUsageDayWindow(days);
  const { data, loading } = useFetchMyUsage(window);
  const { data: quota, loading: quotaLoading } = useFetchQuotaStatus();

  const accounting = data?.accounting;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col">
          <h3 className="text-sm text-text-primary">{t('usage.myUsage')}</h3>
          <span className="text-xs text-text-secondary">
            {t('usage.windowLabel', {
              start: window.start_day,
              end: window.end_day,
            })}
          </span>
        </div>
        <UsageRangeFilter value={days} onChange={setDays} />
      </div>

      {loading && !data ? (
        <CardSkeleton />
      ) : !data || !accounting ? (
        <ComingDataPanel
          testId="my-usage-unavailable"
          tone="unavailable"
          titleKey="usage.unavailableTitle"
          descriptionKey="usage.unavailableDescription"
        />
      ) : (
        <>
          <UsageTotalsGrid
            attemptedCalls={accounting.attempted_calls}
            settledTokens={accounting.settled_tokens}
            outstandingTokens={accounting.outstanding_reserved_tokens}
            effectiveTokens={accounting.effective_tokens}
          />

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <EstimatedCostTile
              label={t('usage.settledEstimatedCost')}
              micros={accounting.settled_estimated_cost_micros}
              coverage={accounting.settled_cost_coverage}
              testId="my-usage-settled-cost"
            />
            <EstimatedCostTile
              label={t('usage.outstandingEstimatedCost')}
              micros={accounting.outstanding_reserved_cost_micros}
              coverage={accounting.outstanding_cost_coverage}
              testId="my-usage-outstanding-cost"
            />
          </div>

          <div className="ceramic-relief flex flex-col gap-1 rounded-[2px] p-3">
            <span className="text-xs text-text-secondary">
              {t('usage.estimatedCostTerm', { term: data.cost.term })}
            </span>
            <span className="text-xs text-text-disabled">
              {t('usage.estimatedCostCaveat')}
            </span>
          </div>
        </>
      )}

      {quotaLoading && !quota ? (
        <CardSkeleton />
      ) : quota?.data ? (
        <div className="ceramic-relief flex flex-col rounded-[2px] p-3">
          <span className="pb-2 text-sm text-text-primary">
            {t('usage.myQuotaTitle')}
          </span>
          <LimitStandingList quota={quota} />
        </div>
      ) : null}
    </div>
  );
}

export default MyUsage;
