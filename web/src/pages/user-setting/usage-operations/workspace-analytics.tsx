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
} from '@/interfaces/database/workspace-usage';
import {
  useFetchDailyUsageSeries,
  useFetchMemberUsageBreakdown,
  useFetchMonthlyUsageSeries,
  useFetchRecordedModelUsage,
  useFetchWorkspaceUsageSummary,
} from '@/hooks/use-workspace-usage-request';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AnalyticsSection } from './components/analytics-section';
import { MemberUsageReport } from './components/member-usage-report';
import { ReadModelNotice } from './components/read-model-notice';
import { ReconciliationStrip } from './components/reconciliation-strip';
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
 * Workspace Analytics: OWNER/ADMIN only.
 *
 * Each block fires its own read, so a reader who only wants the model breakdown
 * does not pay for the series. Nothing is computed here: the reconciliation
 * verdict is the server's own flag rather than a second sum that could drift from
 * the server's.
 *
 * The page's day window is the ONE window: every block below is asked for the same
 * `[start_day, end_day]`, and a member's report inherits it, so a figure in a
 * report and the same member's row above it describe the same interval.
 */
function WorkspaceAnalytics() {
  const { t } = useTranslation();
  const [days, setDays] = useState<UsageRangeDays>(30);
  const window = useUsageDayWindow(days);
  // ONE member report at a time: which row is open belongs to the page, so the
  // table never keeps its own copy of that decision.
  const [openMemberId, setOpenMemberId] = useState<string | null>(null);

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

  const toggleMember = (userId: string) =>
    setOpenMemberId((current) => (current === userId ? null : userId));

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
            <MemberUsageTable
              members={memberData?.members ?? []}
              openUserId={openMemberId}
              onToggle={toggleMember}
              renderReport={(member) => (
                <MemberUsageReport member={member} window={window} />
              )}
            />
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
            hint={t('usage.dailySeriesHint')}
            loading={daily.loading && !dailyData}
            failed={Boolean(daily.error)}
            onRetry={daily.refetch}
            empty={!dailyData?.buckets?.length}
            testId="daily-series-unavailable"
          >
            {/* The table shows the latest 7 days and expands to the whole window.
                The key restarts that choice when the window changes, so a range the
                reader has not looked at yet always opens on its own latest 7 days. */}
            <UsageSeriesTable
              key={`${window.start_day}:${window.end_day}`}
              granularity="day"
              previewLimit={7}
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
            collapsible
            defaultOpen={false}
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
