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

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  IMemberUsageRow,
  IModelUsageRow,
  ISeriesBucket,
  IUsageAccounting,
} from '@/interfaces/database/workspace-usage';
import { cn } from '@/lib/utils';
import { getRoleDisplayConfig } from '@/utils/tenant-role';
import dayjs from 'dayjs';
import { ArrowDown, ArrowUp, ChevronDown, ChevronUp } from 'lucide-react';
import { Fragment, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { formatCount, resolveCostDisplay } from './usage-format';

/* One row language for every settings table: 44px rows, a hairline between them
   and the house zebra pair, so a usage table and a roster table are the same
   object instead of two dialects of a table. */
const settingsRow = 'settings-table-row';

/** A cost cell: the sum, or "Not available" - never `$0.00` without a price. */
function CostCell({
  micros,
  coverage,
}: {
  micros: number | null | undefined;
  coverage: IUsageAccounting['cost_coverage'];
}) {
  const { t } = useTranslation();
  const display = resolveCostDisplay(micros, coverage);

  if (display.kind === 'unavailable') {
    return (
      <span className="font-sans text-text-disabled">
        {t('usage.costNotAvailable')}
      </span>
    );
  }

  return (
    <span className="flex items-baseline justify-end gap-1.5">
      {display.usd}
      {display.kind === 'partial' && (
        <span className="text-xs text-state-warning">
          {t('usage.costPartial')}
        </span>
      )}
    </span>
  );
}

function AccountingCells({ accounting }: { accounting: IUsageAccounting }) {
  return (
    <>
      <TableCell className="settings-table-cell text-end tabular-nums">
        {formatCount(accounting.settled_tokens)}
      </TableCell>
      <TableCell className="settings-table-cell text-end tabular-nums">
        {formatCount(accounting.outstanding_reserved_tokens)}
      </TableCell>
      <TableCell className="settings-table-cell text-end tabular-nums">
        <CostCell
          micros={accounting.settled_estimated_cost_micros}
          coverage={accounting.settled_cost_coverage}
        />
      </TableCell>
    </>
  );
}

/**
 * `GET /usage/daily` and `/usage/monthly` render through this one table.
 *
 * With `previewLimit`, the table shows the LATEST that many periods and offers one
 * control to expand to every period in the requested window and collapse back. The
 * preview is a view choice, not a filter: the collapsed table still shows the
 * recent periods, and the total row count always comes from the window the read
 * model returned.
 */
export function UsageSeriesTable({
  buckets,
  granularity,
  previewLimit,
}: {
  buckets: ISeriesBucket[];
  granularity: 'day' | 'month';
  previewLimit?: number;
}) {
  const { t } = useTranslation();
  const [descending, setDescending] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const tableId = useId();
  // Choose the latest periods FIRST, then present them newest first, so a preview is
  // the newest end of the window whatever order the server sent.
  const newestFirst = [...buckets].sort((a, b) =>
    b.period.localeCompare(a.period),
  );
  const visible =
    previewLimit && !expanded ? newestFirst.slice(0, previewLimit) : newestFirst;
  const rows = descending ? visible : [...visible].reverse();
  const today = dayjs().format('YYYY-MM-DD');
  const yesterday = dayjs().subtract(1, 'day').format('YYYY-MM-DD');
  const toggleSort = () => setDescending((value) => !value);
  const toggleExpanded = () => setExpanded((value) => !value);
  const SortIcon = descending ? ArrowDown : ArrowUp;
  const ExpandIcon = expanded ? ChevronUp : ChevronDown;

  return (
    <div id={tableId}>
      <Table
        rootClassName="settings-table [&_td]:py-0 [&_th]:py-0 [&_th]:whitespace-nowrap"
        className="table-fixed [&_td]:overflow-hidden"
      >
        <TableHeader className="bg-table-header">
          <TableRow className="border-b border-table-border hover:bg-table-header">
            <TableHead
              className="settings-table-head-cell text-left"
              aria-sort={descending ? 'descending' : 'ascending'}
            >
              <button
                type="button"
                className="inline-flex h-8 items-center gap-1.5 rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-primary"
                onClick={toggleSort}
                aria-label={t(descending ? 'usage.sortOldestFirst' : 'usage.sortNewestFirst')}
              >
                {granularity === 'day' ? t('usage.day') : t('usage.month')}
                <SortIcon size={14} aria-hidden="true" />
              </button>
            </TableHead>
            <TableHead className="settings-table-head-cell text-end">
              {t('usage.attemptedCalls')}
            </TableHead>
            <TableHead className="settings-table-head-cell text-end">{t('usage.settledTokens')}</TableHead>
            <TableHead className="settings-table-head-cell text-end">
              {t('usage.outstandingTokens')}
            </TableHead>
            <TableHead className="settings-table-head-cell text-end">
              {t('usage.settledEstimatedCost')}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((bucket) => (
            <TableRow key={bucket.period} className={settingsRow}>
              <TableCell className="settings-table-cell text-left tabular-nums">
                <span className="flex items-center gap-1.5 whitespace-nowrap">
                  {bucket.period}
                  {granularity === 'day' &&
                    (bucket.period === today || bucket.period === yesterday) && (
                      <span className="settings-tag shrink-0 text-text-secondary">
                        {t(bucket.period === today ? 'usage.today' : 'usage.yesterday')}
                      </span>
                    )}
                </span>
              </TableCell>
              <TableCell className="settings-table-cell text-end tabular-nums">
                {formatCount(bucket.attempted_calls)}
              </TableCell>
              <AccountingCells accounting={bucket.accounting} />
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {previewLimit && buckets.length > previewLimit && (
        <div className="flex justify-center pt-3">
          <button
            type="button"
            className="settings-control inline-flex min-h-8 items-center justify-center gap-1.5 px-3 text-xs text-text-secondary hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-primary"
            aria-expanded={expanded}
            aria-controls={tableId}
            onClick={toggleExpanded}
          >
            <ExpandIcon size={14} aria-hidden="true" />
            {t(expanded ? 'usage.collapseRecentDays' : 'usage.showAllDays', {
              count: expanded ? previewLimit : buckets.length,
            })}
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * The per-member breakdown.
 *
 * A member who is no longer active keeps their history here - the server reports
 * `live_member: false` rather than dropping the row - so the table labels it
 * instead of hiding usage the workspace really incurred.
 *
 * When `onToggle` is given, a row opens that member's report directly beneath it.
 * WHICH row is open is the caller's state (`openUserId`), so exactly one report can
 * be open at a time; this table never decides that for itself.
 */
export function MemberUsageTable({
  members,
  openUserId,
  onToggle,
  renderReport,
}: {
  members: IMemberUsageRow[];
  openUserId?: string | null;
  onToggle?: (userId: string) => void;
  renderReport?: (member: IMemberUsageRow) => React.ReactNode;
}) {
  const { t } = useTranslation();
  const expandable = Boolean(onToggle && renderReport);

  return (
    <Table
      rootClassName="settings-table [&_td]:py-0 [&_th]:py-0 [&_th]:whitespace-nowrap"
      className="table-fixed [&_td]:overflow-hidden"
    >
      <TableHeader className="bg-table-header">
        <TableRow className="border-b border-table-border hover:bg-table-header">
          <TableHead className="settings-table-head-cell">{t('usage.member')}</TableHead>
          <TableHead className="settings-table-head-cell">{t('setting.role')}</TableHead>
          <TableHead className="settings-table-head-cell text-end">
            {t('usage.attemptedCalls')}
          </TableHead>
          <TableHead className="settings-table-head-cell text-end">{t('usage.settledTokens')}</TableHead>
          <TableHead className="settings-table-head-cell text-end">
            {t('usage.outstandingTokens')}
          </TableHead>
          <TableHead className="settings-table-head-cell text-end">
            {t('usage.settledEstimatedCost')}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {members.map((member) => {
          const open = openUserId === member.user_id;
          const detailId = `member-report-${member.user_id}`;
          return (
            <Fragment key={member.user_id}>
              <TableRow
                className={cn(settingsRow, expandable && 'cursor-pointer')}
                data-testid="member-usage-row"
                onClick={expandable ? () => onToggle?.(member.user_id) : undefined}
              >
                <TableCell className="settings-table-cell">
                  <span className="flex items-center gap-2">
                    {expandable && (
                      <button
                        type="button"
                        className="inline-flex size-5 shrink-0 items-center justify-center text-text-secondary hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-primary"
                        aria-expanded={open}
                        aria-controls={detailId}
                        aria-label={t('usage.memberReport')}
                        data-testid="member-usage-toggle"
                        onClick={(event) => {
                          // The row is a convenience target; the control is the button,
                          // so one click must not toggle twice.
                          event.stopPropagation();
                          onToggle?.(member.user_id);
                        }}
                      >
                        {open ? (
                          <ChevronUp size={14} aria-hidden="true" />
                        ) : (
                          <ChevronDown size={14} aria-hidden="true" />
                        )}
                      </button>
                    )}
                    {member.nickname || member.user_id}
                  </span>
                </TableCell>
                <TableCell className="settings-table-cell">
                  <span className="flex items-center gap-2">
                    {/* The same tag the roster uses for a role, so a role reads the
                        same in a settings table and in a usage table. */}
                    <span className="settings-tag text-content-secondary">
                      {/* A removed member has no role any more; the shared role helper
                          renders its neutral label rather than inventing one. */}
                      {t(getRoleDisplayConfig(member.role ?? undefined).labelKey)}
                    </span>
                    {!member.live_member && (
                      <span className="settings-field-hint">
                        {t('usage.memberRemoved')}
                      </span>
                    )}
                  </span>
                </TableCell>
                <TableCell className="settings-table-cell text-end tabular-nums">
                  {formatCount(member.accounting.attempted_calls)}
                </TableCell>
                <AccountingCells accounting={member.accounting} />
              </TableRow>
              {open && renderReport && (
                <TableRow
                  className="hover:bg-transparent"
                  data-testid="member-usage-report-row"
                >
                  <TableCell colSpan={6} className="settings-table-cell">
                    <div id={detailId}>{renderReport(member)}</div>
                  </TableCell>
                </TableRow>
              )}
            </Fragment>
          );
        })}
      </TableBody>
    </Table>
  );
}

/**
 * The recorded-model breakdown.
 *
 * The name is what the ledger RECORDED. Provider and key-instance attribution are
 * not recorded anywhere and are never reconstructed, so the table shows the name
 * alone and marks an empty one as the unrecorded bucket.
 */
export function RecordedModelUsageTable({
  models,
}: {
  models: IModelUsageRow[];
}) {
  const { t } = useTranslation();

  return (
    <Table
      rootClassName="settings-table [&_td]:py-0 [&_th]:py-0 [&_th]:whitespace-nowrap"
      className="table-fixed [&_td]:overflow-hidden"
    >
      <TableHeader className="bg-table-header">
        <TableRow className="border-b border-table-border hover:bg-table-header">
          <TableHead className="settings-table-head-cell">
            {t('usage.recordedModel')}
          </TableHead>
          <TableHead className="settings-table-head-cell text-end">
            {t('usage.attemptedCalls')}
          </TableHead>
          <TableHead className="settings-table-head-cell text-end">{t('usage.settledTokens')}</TableHead>
          <TableHead className="settings-table-head-cell text-end">
            {t('usage.outstandingTokens')}
          </TableHead>
          <TableHead className="settings-table-head-cell text-end">
            {t('usage.settledEstimatedCost')}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {models.map((model) => (
          <TableRow key={model.bucket} className={settingsRow}>
            <TableCell
              className={cn(
                'settings-table-cell',
                model.recorded_model_name ? undefined : 'text-text-disabled',
              )}
            >
              {model.recorded_model_name ?? t('usage.modelUnrecorded')}
            </TableCell>
            <TableCell className="settings-table-cell text-end tabular-nums">
              {formatCount(model.accounting.attempted_calls)}
            </TableCell>
            <AccountingCells accounting={model.accounting} />
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
