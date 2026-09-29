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
  IMemberBreakdownData,
  IRecordedModelBreakdownData,
  ISeriesData,
  IUsageEnvelope,
} from '@/interfaces/database/workspace-usage';
import {
  useFetchDailyUsageSeries,
  useFetchMemberUsageBreakdown,
  useFetchMonthlyUsageSeries,
  useFetchRecordedModelUsage,
  useFetchWorkspaceUsageSummary,
} from '@/hooks/use-workspace-usage-request';
import { cn } from '@/lib/utils';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ComingDataPanel } from './components/coming-data-panel';
import { EstimatedCostTile, UsageTotalsGrid } from './components/usage-metric';
import {
  UsageRangeDays,
  UsageRangeFilter,
  useUsageDayWindow,
} from './components/usage-range-filter';
import {
  MemberUsageTable,
  RecordedModelUsageTable,
  UsageSeriesTable,
} from './components/usage-tables';

/**
 * The reconciliation strip.
 *
 * The counters and the ledger are two records of the same attempts, and nothing
 * reconciles them automatically, so when they disagree the reader is TOLD rather
 * than shown whichever figure looks better. Both numbers are on screen either
 * way.
 */
function ReconciliationStrip({ payload }: { payload: IUsageEnvelope }) {
  const { t } = useTranslation();
  const reconciliation = payload.reconciliation;

  if (!reconciliation) {
    return null;
  }

  const consistent =
    reconciliation.calls_consistent && reconciliation.tokens_consistent;

  return (
    <div
      className="ceramic-relief flex flex-col gap-1 rounded-[2px] p-3"
      data-testid="usage-reconciliation"
    >
      <span className="text-xs text-text-secondary">
        {t('usage.reconciliationTitle')}
      </span>
      <span
        className={cn(
          'text-xs',
          consistent ? 'text-text-secondary' : 'text-state-warning',
        )}
      >
        {consistent
          ? t('usage.reconciliationConsistent')
          : t('usage.reconciliationDivergent', {
              ledger: reconciliation.ledger_attempted_calls,
              counter: reconciliation.counter_calls,
            })}
      </span>
      <span className="text-xs text-text-disabled">
        {reconciliation.semantics}
      </span>
    </div>
  );
}

/**
 * Workspace Analytics: OWNER/ADMIN only.
 *
 * The page mounts only for a manager, and each block fires its own query, so a
 * NORMAL member never issues a workspace-aggregate request the server would
 * refuse. Nothing here is computed on the client: `sum(member_breakdown)` is the
 * server's own reconciliation flag, not a second calculation that could drift
 * from it.
 */
function WorkspaceAnalytics() {
  const { t } = useTranslation();
  const [days, setDays] = useState<UsageRangeDays>(31);
  const window = useUsageDayWindow(days);

  const summary = useFetchWorkspaceUsageSummary(window);
  const members = useFetchMemberUsageBreakdown({ ...window, limit: 50 });
  const models = useFetchRecordedModelUsage({ ...window, limit: 50 });
  const daily = useFetchDailyUsageSeries(window);
  const monthly = useFetchMonthlyUsageSeries();

  const accounting = summary.data?.accounting;
  const memberData = members.data?.data as IMemberBreakdownData | undefined;
  const modelData = models.data?.data as
    | IRecordedModelBreakdownData
    | undefined;
  const dailyData = daily.data?.data as ISeriesData | undefined;
  const monthlyData = monthly.data?.data as ISeriesData | undefined;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col">
          <h3 className="text-sm text-text-primary">
            {t('usage.workspaceAnalytics')}
          </h3>
          <span className="text-xs text-text-secondary">
            {t('usage.windowLabel', {
              start: window.start_day,
              end: window.end_day,
            })}
          </span>
        </div>
        <UsageRangeFilter value={days} onChange={setDays} />
      </div>

      {summary.loading && !summary.data ? (
        <CardSkeleton />
      ) : !summary.data || !accounting ? (
        <ComingDataPanel
          testId="workspace-summary-unavailable"
          tone="unavailable"
          titleKey="usage.unavailableTitle"
          descriptionKey="usage.workspaceUnavailableDescription"
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
              testId="workspace-settled-cost"
            />
            <EstimatedCostTile
              label={t('usage.outstandingEstimatedCost')}
              micros={accounting.outstanding_reserved_cost_micros}
              coverage={accounting.outstanding_cost_coverage}
              testId="workspace-outstanding-cost"
            />
          </div>

          <ReconciliationStrip payload={summary.data} />

          <section className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between gap-2">
              <h4 className="text-sm text-text-primary">
                {t('usage.memberBreakdown')}
              </h4>
              {memberData?.truncated && (
                <span className="text-xs text-text-disabled">
                  {t('usage.truncatedNotice', {
                    total: memberData.total_members,
                  })}
                </span>
              )}
            </div>
            {members.loading && !memberData ? (
              <CardSkeleton />
            ) : memberData?.members?.length ? (
              <MemberUsageTable members={memberData.members} />
            ) : (
              <ComingDataPanel
                tone="unavailable"
                testId="member-breakdown-empty"
                titleKey="usage.noMeteredActivityTitle"
                descriptionKey="usage.noMeteredActivityDescription"
              />
            )}
          </section>

          <section className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between gap-2">
              <h4 className="text-sm text-text-primary">
                {t('usage.recordedModelBreakdown')}
              </h4>
              {modelData?.truncated && (
                <span className="text-xs text-text-disabled">
                  {t('usage.truncatedNotice', {
                    total: modelData.total_buckets,
                  })}
                </span>
              )}
            </div>
            {models.loading && !modelData ? (
              <CardSkeleton />
            ) : modelData?.models?.length ? (
              <>
                <RecordedModelUsageTable models={modelData.models} />
                <p className="text-xs text-text-disabled">
                  {modelData.not_answered}
                </p>
              </>
            ) : (
              <ComingDataPanel
                tone="unavailable"
                testId="model-breakdown-empty"
                titleKey="usage.noMeteredActivityTitle"
                descriptionKey="usage.noMeteredActivityDescription"
              />
            )}
          </section>

          <section className="flex flex-col gap-2">
            <h4 className="text-sm text-text-primary">
              {t('usage.dailySeries')}
            </h4>
            {daily.loading && !dailyData ? (
              <CardSkeleton />
            ) : dailyData?.buckets?.length ? (
              <>
                <UsageSeriesTable granularity="day" buckets={dailyData.buckets} />
                <p className="text-xs text-text-disabled">
                  {dailyData.zero_filled}
                </p>
              </>
            ) : (
              <ComingDataPanel
                tone="unavailable"
                testId="daily-series-empty"
                titleKey="usage.noMeteredActivityTitle"
                descriptionKey="usage.noMeteredActivityDescription"
              />
            )}
          </section>

          <section className="flex flex-col gap-2">
            <h4 className="text-sm text-text-primary">
              {t('usage.monthlySeries')}
            </h4>
            <p className="text-xs text-text-disabled">
              {t('usage.monthlySeriesHint')}
            </p>
            {monthly.loading && !monthlyData ? (
              <CardSkeleton />
            ) : monthlyData?.buckets?.length ? (
              <UsageSeriesTable
                granularity="month"
                buckets={monthlyData.buckets}
              />
            ) : (
              <ComingDataPanel
                tone="unavailable"
                testId="monthly-series-empty"
                titleKey="usage.noMeteredActivityTitle"
                descriptionKey="usage.noMeteredActivityDescription"
              />
            )}
          </section>
        </>
      )}
    </div>
  );
}

export default WorkspaceAnalytics;
