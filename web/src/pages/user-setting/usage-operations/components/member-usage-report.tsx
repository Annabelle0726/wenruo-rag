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
  IMemberUsageRow,
  IUsageRangeParams,
} from '@/interfaces/database/workspace-usage';
import { useFetchMemberReport } from '@/hooks/use-workspace-usage-request';
import { getRoleDisplayConfig } from '@/utils/tenant-role';
import { useTranslation } from 'react-i18next';
import { AnalyticsSection } from './analytics-section';
import { ReadModelNotice } from './read-model-notice';
import { ReconciliationStrip } from './reconciliation-strip';
import { EstimatedCostTile, UsageTotalsGrid } from './usage-metric';
import {
  RecordedModelUsageTable,
  UsageSeriesTable,
} from './usage-tables';

/**
 * One member's usage report, rendered inside that member's row.
 *
 * Every figure comes from `GET /usage/member-report`, which is the workspace read
 * model scoped to one member: the totals, the per-day and per-month buckets, the
 * recorded-model buckets, the reconciliation block and the cost coverage are the
 * server's own. NOTHING is recomputed here - the browser formats numbers and never
 * adds, derives or estimates one - so this panel cannot disagree with the member's
 * row in the table above it.
 *
 * Four states are separated on purpose:
 *
 * - **loading**: a read is in flight;
 * - **failed**: the read was refused or failed, reported AS a failure with a retry.
 *   A failure is never rendered as "no usage", which is the confusion a usage page
 *   exists to avoid;
 * - **empty**: the read succeeded and this member recorded no metered attempt in
 *   the window. The panel says exactly that instead of drawing a report of zeros,
 *   because zero attempts is an absence of records, not a measurement of zero;
 * - **ready**: the report.
 */
export function MemberUsageReport({
  member,
  window,
}: {
  member: IMemberUsageRow;
  window: IUsageRangeParams;
}) {
  const { t } = useTranslation();
  const { data, loading, error, refetch } = useFetchMemberReport(
    member.user_id,
    window,
  );

  const report = data?.data;
  const accounting = data?.accounting;
  const subject = report?.member;
  const nickname = subject?.nickname ?? member.nickname;
  const liveMember = subject?.live_member ?? member.live_member;
  const role = subject?.role ?? member.role;
  const roleLabel = t(getRoleDisplayConfig(role ?? undefined).labelKey);

  const identity = (
    <div className="flex flex-wrap items-center gap-2" data-testid="member-report-identity">
      <span className="text-sm font-semibold text-text-primary">
        {nickname || member.user_id}
      </span>
      <span className="settings-tag text-content-secondary">{roleLabel}</span>
      {!liveMember && (
        <span className="settings-field-hint">{t('usage.memberRemoved')}</span>
      )}
      {/* A stable identifier: a name is mutable and a removed member has no
          profile left, so the id is what a reader can quote. */}
      <span
        className="settings-field-hint tabular-nums"
        title={member.user_id}
        data-testid="member-report-id"
      >
        {t('usage.memberReportId')} {member.user_id.slice(0, 8)}
      </span>
    </div>
  );

  if (loading && !data) {
    return (
      <div data-testid="member-report-loading">
        {identity}
        <CardSkeleton />
      </div>
    );
  }

  if (error || !data || !accounting) {
    return (
      <div className="flex flex-col gap-2" data-testid="member-report-failed">
        {identity}
        <ReadModelNotice
          failed
          onRetry={refetch}
          testId="member-report-unavailable"
        />
      </div>
    );
  }

  // The read answered; this member simply recorded nothing in the window.
  if (accounting.attempted_calls === 0) {
    return (
      <div className="flex flex-col gap-2" data-testid="member-report-empty">
        {identity}
        <ReadModelNotice failed={false} onRetry={refetch} testId="member-report-no-rows" />
      </div>
    );
  }

  const period = data.period;

  return (
    <div className="flex flex-col gap-3" data-testid="member-report-ready">
      {identity}

      <span className="settings-section-hint tabular-nums">
        {t('usage.windowLabel', {
          start: period.start_day,
          end: period.end_day,
        })}
        {typeof period.days === 'number'
          ? ` · ${t('usage.windowDays', { count: period.days })}`
          : ''}
      </span>

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
          testId="member-report-settled-cost"
        />
        <EstimatedCostTile
          label={t('usage.outstandingEstimatedCost')}
          micros={accounting.outstanding_reserved_cost_micros}
          coverage={accounting.outstanding_cost_coverage}
          testId="member-report-outstanding-cost"
        />
      </div>

      {/* The payload's own reconciliation block, never a second sum. */}
      <ReconciliationStrip payload={data} testId="member-report-reconciliation" />

      <AnalyticsSection
        title={t('usage.dailySeries')}
        hint={t('usage.dailySeriesHint')}
        loading={false}
        failed={false}
        onRetry={refetch}
        empty={!report?.daily?.buckets?.length}
        testId="member-daily-series-unavailable"
      >
        <UsageSeriesTable
          granularity="day"
          previewLimit={7}
          buckets={report?.daily?.buckets ?? []}
        />
      </AnalyticsSection>

      <AnalyticsSection
        title={t('usage.monthlySeries')}
        hint={t('usage.monthlySeriesHint')}
        loading={false}
        failed={false}
        onRetry={refetch}
        empty={!report?.monthly?.buckets?.length}
        testId="member-monthly-series-unavailable"
        collapsible
        defaultOpen={false}
      >
        <UsageSeriesTable
          granularity="month"
          buckets={report?.monthly?.buckets ?? []}
        />
      </AnalyticsSection>

      <AnalyticsSection
        title={t('usage.recordedModelBreakdown')}
        hint={t('usage.modelAttributionCaveat')}
        loading={false}
        failed={false}
        onRetry={refetch}
        empty={!report?.models?.models?.length}
        testId="member-model-breakdown-unavailable"
      >
        <RecordedModelUsageTable models={report?.models?.models ?? []} />
      </AnalyticsSection>
    </div>
  );
}

export default MemberUsageReport;
