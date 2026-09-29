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

import { Badge } from '@/components/ui/badge';
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

const zebraRow = 'odd:bg-bg-list';

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
      <TableCell className="text-end tabular-nums">
        {formatCount(accounting.settled_tokens)}
      </TableCell>
      <TableCell className="text-end tabular-nums">
        {formatCount(accounting.outstanding_reserved_tokens)}
      </TableCell>
      <TableCell className="text-end tabular-nums">
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
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>
            {granularity === 'day' ? t('usage.day') : t('usage.month')}
          </TableHead>
          <TableHead className="text-end">{t('usage.attemptedCalls')}</TableHead>
          <TableHead className="text-end">{t('usage.settledTokens')}</TableHead>
          <TableHead className="text-end">
            {t('usage.outstandingTokens')}
          </TableHead>
          <TableHead className="text-end">
            {t('usage.settledEstimatedCost')}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {buckets.map((bucket) => (
          <TableRow key={bucket.period} className={zebraRow}>
            <TableCell className="tabular-nums">{bucket.period}</TableCell>
            <TableCell className="text-end tabular-nums">
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
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t('usage.member')}</TableHead>
          <TableHead>{t('setting.role')}</TableHead>
          <TableHead className="text-end">{t('usage.attemptedCalls')}</TableHead>
          <TableHead className="text-end">{t('usage.settledTokens')}</TableHead>
          <TableHead className="text-end">
            {t('usage.outstandingTokens')}
          </TableHead>
          <TableHead className="text-end">
            {t('usage.settledEstimatedCost')}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {members.map((member) => (
          <TableRow key={member.user_id} className={zebraRow}>
            <TableCell className="max-w-[220px] truncate">
              {member.nickname || member.user_id}
            </TableCell>
            <TableCell>
              <span className="flex items-center gap-2">
                <Badge className="rounded-[2px]">
                  {/* A removed member has no role any more; the shared role helper
                      renders its neutral label rather than inventing one. */}
                  {t(getRoleDisplayConfig(member.role ?? undefined).labelKey)}
                </Badge>
                {!member.live_member && (
                  <span className="text-xs text-text-disabled">
                    {t('usage.memberRemoved')}
                  </span>
                )}
              </span>
            </TableCell>
            <TableCell className="text-end tabular-nums">
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
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t('usage.recordedModel')}</TableHead>
          <TableHead className="text-end">{t('usage.attemptedCalls')}</TableHead>
          <TableHead className="text-end">{t('usage.settledTokens')}</TableHead>
          <TableHead className="text-end">
            {t('usage.outstandingTokens')}
          </TableHead>
          <TableHead className="text-end">
            {t('usage.settledEstimatedCost')}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {models.map((model) => (
          <TableRow key={model.bucket} className={zebraRow}>
            <TableCell
              className={cn(
                'max-w-[260px] truncate',
                model.recorded_model_name ? undefined : 'text-text-disabled',
              )}
            >
              {model.recorded_model_name ?? t('usage.modelUnrecorded')}
            </TableCell>
            <TableCell className="text-end tabular-nums">
              {formatCount(model.accounting.attempted_calls)}
            </TableCell>
            <AccountingCells accounting={model.accounting} />
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
