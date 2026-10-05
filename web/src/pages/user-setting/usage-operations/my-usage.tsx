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
import { LimitStandingList } from './components/limit-standing-list';
import { ReadModelNotice } from './components/read-model-notice';
import { EstimatedCostTile, UsageTotalsGrid } from './components/usage-metric';
import {
  UsageRangeDays,
  UsageRangeFilter,
  useUsageDayWindow,
} from './components/usage-range-filter';

/**
 * My Usage: the caller's OWN metered usage and current quota standing.
 *
 * It is the one destination every member has, and its subject is the reader
 * rather than the workspace - the server forces that, so this view cannot be
 * pointed at another member's rows even if it tried.
 *
 * There is deliberately NO per-day chart: a member's own daily series does not
 * exist in the read model (`daily_series` is a workspace-aggregate view the server
 * refuses to a NORMAL caller), and drawing a trend from the window total would
 * show a shape the records do not support.
 */
function MyUsage() {
  const { t } = useTranslation();
  const [days, setDays] = useState<UsageRangeDays>(30);
  const window = useUsageDayWindow(days);
  const { data, loading, refetch, error } = useFetchMyUsage(window);
  const {
    data: quota,
    loading: quotaLoading,
    refetch: refetchQuota,
    error: quotaError,
  } = useFetchQuotaStatus();

  const accounting = data?.accounting;

  return (
    <div className="settings-body">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="settings-section-hint tabular-nums">
          {t('usage.windowLabel', {
            start: window.start_day,
            end: window.end_day,
          })}
        </span>
        <UsageRangeFilter value={days} onChange={setDays} />
      </div>

      {loading && !data ? (
        <CardSkeleton />
      ) : !accounting ? (
        <ReadModelNotice
          testId="my-usage-unavailable"
          failed={Boolean(error)}
          onRetry={refetch}
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
        </>
      )}

      {/* The quota standing is a section of its own: a hairline heading, the seven
          dimensions and the caveats, with no card of its own. */}
      <section className="settings-section">
        <div className="settings-section-head">
          <h3 className="settings-section-title">
            {t('usage.myQuotaTitle')}
          </h3>
        </div>
        <div className="settings-section-body">
          {quotaLoading && !quota ? (
            <CardSkeleton />
          ) : quota?.data ? (
            <LimitStandingList quota={quota} />
          ) : (
            <ReadModelNotice
              testId="my-quota-unavailable"
              failed={Boolean(quotaError)}
              onRetry={refetchQuota}
            />
          )}
        </div>
      </section>

      {accounting && data && (
        <div className="flex flex-col gap-0.5">
          <span className="settings-field-hint">
            {t('usage.estimatedCostTerm', { term: data.cost.term })}
          </span>
          <span className="settings-field-hint">
            {t('usage.estimatedCostCaveat')}
          </span>
        </div>
      )}
    </div>
  );
}

export default MyUsage;
