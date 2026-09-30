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
      <span className="text-text-disabled">{t('usage.costNotAvailable')}</span>
    );
  }

  return (
    <span className="flex items-baseline gap-1.5">
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

/** `GET /usage/daily` and `/usage/monthly` render through this one table. */
export function UsageSeriesTable({
  buckets,
  granularity,
}: {
  buckets: ISeriesBucket[];
  granularity: 'day' | 'month';
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
            {granularity === 'day' ? t('usage.day') : t('usage.month')}
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
        {buckets.map((bucket) => (
          <TableRow key={bucket.period} className={settingsRow}>
            <TableCell className="settings-table-cell tabular-nums">{bucket.period}</TableCell>
            <TableCell className="settings-table-cell text-end tabular-nums">
              {formatCount(bucket.attempted_calls)}
            </TableCell>
            <AccountingCells accounting={bucket.accounting} />
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * The per-member breakdown.
 *
 * A member who is no longer active keeps their history here - the server reports
 * `live_member: false` rather than dropping the row - so the table labels it
 * instead of hiding usage the workspace really incurred.
 */
export function MemberUsageTable({ members }: { members: IMemberUsageRow[] }) {
  const { t } = useTranslation();

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
        {members.map((member) => (
          <TableRow key={member.user_id} className={settingsRow}>
            <TableCell className="settings-table-cell">
              {member.nickname || member.user_id}
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
        ))}
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
          <TableHead className="settings-table-head-cell">{t('usage.recordedModel')}</TableHead>
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
