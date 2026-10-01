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
import { EstimatedCostTile, UsageTotalsGrid } from './components/usage-metric';
import { ReadModelNotice } from './components/read-model-notice';
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
 * The counters and the ledger are two records of the same attempts and nothing
 * reconciles them automatically, so a disagreement is TOLD to the reader rather
 * than resolved by showing whichever figure looks better. Both numbers are on
 * screen either way.
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
      className="settings-tile"
      data-testid="usage-reconciliation"
    >
      <span className="settings-tile-label">
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
      <span className="settings-tile-hint">
        {t('usage.reconciliationSemantics')}
      </span>
    </div>
  );
}

/**
 * One block of the analytics page, so every block states its own three states the
 * same way: loading, a failure that the block owns, or content.
 */
function AnalyticsSection({
  title,
  hint,
  loading,
  failed,
  onRetry,
  empty,
  testId,
  children,
}: {
  title: string;
  hint?: string;
  loading: boolean;
  failed: boolean;
  onRetry: () => void;
  empty: boolean;
  testId: string;
  children: React.ReactNode;
}) {
  return (
    <section className="settings-section">
      <div className="settings-section-head">
        <h3 className="settings-section-title">{title}</h3>
        {hint && <p className="settings-section-hint">{hint}</p>}
      </div>
      <div className="settings-section-body">
        {loading ? (
          <CardSkeleton />
        ) : failed || empty ? (
          <ReadModelNotice failed={failed} onRetry={onRetry} testId={testId} />
        ) : (
          children
        )}
      </div>
    </section>
  );
}

/**
 * Workspace Analytics: OWNER/ADMIN only.
 *
 * Each block fires its own read, so a reader who only wants the model breakdown
 * does not pay for the series. Nothing is computed here: the reconciliation
 * verdict is the server's own flag rather than a second sum that could drift from
 * the server's.
 */
function WorkspaceAnalytics() {
  const { t } = useTranslation();
  const [days, setDays] = useState<UsageRangeDays>(30);
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

      {summary.loading && !summary.data ? (
        <CardSkeleton />
      ) : !accounting ? (
        <ReadModelNotice
          testId="workspace-summary-unavailable"
          failed={Boolean(summary.error)}
          onRetry={summary.refetch}
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

          {summary.data && <ReconciliationStrip payload={summary.data} />}

          <AnalyticsSection
            title={t('usage.memberBreakdown')}
            hint={
              memberData?.truncated
                ? t('usage.truncatedNotice', {
                    total: memberData.total_members,
                  })
                : undefined
            }
            loading={members.loading && !memberData}
            failed={Boolean(members.error)}
            onRetry={members.refetch}
            empty={!memberData?.members?.length}
            testId="member-breakdown-unavailable"
          >
            <MemberUsageTable members={memberData?.members ?? []} />
          </AnalyticsSection>

          <AnalyticsSection
            title={t('usage.recordedModelBreakdown')}
            hint={
              modelData?.truncated
                ? t('usage.truncatedNotice', {
                    total: modelData.total_buckets,
                  })
                : t('usage.modelAttributionCaveat')
            }
            loading={models.loading && !modelData}
            failed={Boolean(models.error)}
            onRetry={models.refetch}
            empty={!modelData?.models?.length}
            testId="model-breakdown-unavailable"
          >
            <RecordedModelUsageTable models={modelData?.models ?? []} />
          </AnalyticsSection>

          <AnalyticsSection
            title={t('usage.dailySeries')}
            hint={dailyData?.zero_filled}
            loading={daily.loading && !dailyData}
            failed={Boolean(daily.error)}
            onRetry={daily.refetch}
            empty={!dailyData?.buckets?.length}
            testId="daily-series-unavailable"
          >
            <UsageSeriesTable
              granularity="day"
              buckets={dailyData?.buckets ?? []}
            />
          </AnalyticsSection>

          <AnalyticsSection
            title={t('usage.monthlySeries')}
            hint={t('usage.monthlySeriesHint')}
            loading={monthly.loading && !monthlyData}
            failed={Boolean(monthly.error)}
            onRetry={monthly.refetch}
            empty={!monthlyData?.buckets?.length}
            testId="monthly-series-unavailable"
          >
            <UsageSeriesTable
              granularity="month"
              buckets={monthlyData?.buckets ?? []}
            />
          </AnalyticsSection>
        </>
      )}
    </div>
  );
}

export default WorkspaceAnalytics;
