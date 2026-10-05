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
  IUsageEnvelope,
  IUsageLimitStanding,
} from '@/interfaces/database/workspace-usage';
import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';
import { formatCount, formatMicrosAsUsd } from './usage-format';

/** The seven limit dimensions, in the order the server reports them. */
const DIMENSION_LABEL_KEYS: Array<[string, string]> = [
  ['calls_per_minute', 'usage.limitCallsPerMinute'],
  ['calls_per_day', 'usage.limitCallsPerDay'],
  ['calls_per_month', 'usage.limitCallsPerMonth'],
  ['tokens_per_day', 'usage.limitTokensPerDay'],
  ['tokens_per_month', 'usage.limitTokensPerMonth'],
  ['cost_micros_per_day', 'usage.limitCostPerDay'],
  ['cost_micros_per_month', 'usage.limitCostPerMonth'],
];

const COST_DIMENSIONS = new Set([
  'cost_micros_per_day',
  'cost_micros_per_month',
]);

const formatLimitValue = (dimension: string, value: number): string => {
  if (COST_DIMENSIONS.has(dimension)) {
    return formatMicrosAsUsd(value);
  }
  return formatCount(value);
};

/**
 * One limit row: the configured value, the occupancy it is measured against, and
 * the three states a reader must be able to tell apart.
 *
 * A limit of 0 is "this dimension is not enforced", NOT "zero remaining", and an
 * exempt manager is told so instead of being shown a bar they can never fail.
 * The rolling minute has no occupancy in this read model at all (it lives in
 * Redis), so it reports that its usage is unavailable rather than a number.
 */
function LimitRow({
  dimension,
  labelKey,
  standing,
}: {
  dimension: string;
  labelKey: string;
  standing: IUsageLimitStanding | undefined;
}) {
  const { t } = useTranslation();

  if (!standing) {
    return null;
  }

  const notEnforced = !standing.enforced;
  const usedText = standing.used_available
    ? formatLimitValue(dimension, standing.used ?? 0)
    : t('usage.usedUnavailable');
  const remainingText =
    standing.remaining === null || standing.remaining === undefined
      ? null
      : formatLimitValue(dimension, standing.remaining);

  // The bar is only drawn for an enforced, measurable, non-exempt limit: a bar
  // over an unenforced dimension would read as a quota that exists.
  const measurable =
    standing.enforced && standing.used_available && standing.exempt !== true;
  const ratio =
    measurable && standing.limit > 0
      ? Math.min(1, (standing.used ?? 0) / standing.limit)
      : 0;
  const overLimit =
    measurable && remainingText !== null && (standing.remaining ?? 0) < 0;

  return (
    <div
      className="flex flex-col gap-1.5 py-2.5"
      data-testid={`usage-limit-${dimension}`}
    >
      {/* Label left, configured value right: the two ends of one row, so a column
          of figures lines up on its last digit (`.tabular-nums` on the value). */}
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="text-[13px] text-text-primary">{t(labelKey)}</span>
        <span className="flex items-baseline gap-2 text-xs text-text-secondary tabular-nums">
          <span className="font-mono font-medium tabular-nums">
            {notEnforced && COST_DIMENSIONS.has(dimension)
              ? t('usage.limitNotEnforced')
              : formatLimitValue(dimension, standing.limit)}
          </span>
          {notEnforced && !COST_DIMENSIONS.has(dimension) && (
            <span className="settings-tag text-content-tertiary">
              {/* One message for both cases: whether the dimension is allowed to
                  be zero or the stored value is a legacy zero, it is not enforced
                  and it is never "zero remaining". */}
              {t('usage.limitNotEnforced')}
            </span>
          )}
          {standing.exempt === true && (
            <span className="settings-tag border-state-warning text-state-warning">
              {t('usage.limitExempt')}
            </span>
          )}
        </span>
      </div>

      {measurable && (
        <div className="h-1 w-full overflow-hidden rounded-[2px] bg-bg-input">
          <div
            className={cn(
              'h-full rounded-[2px]',
              overLimit ? 'bg-state-error' : 'bg-accent-primary',
            )}
            style={{ width: `${Math.round(ratio * 100)}%` }}
          />
        </div>
      )}

      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-xs text-text-disabled tabular-nums">
        <span>{t('usage.limitUsed', { value: usedText })}</span>
        {remainingText !== null && (
          <span
            className={cn(
              overLimit ? 'text-state-error' : undefined,
              standing.exempt ? 'text-text-disabled' : undefined,
            )}
          >
            {t('usage.limitRemaining', { value: remainingText })}
          </span>
        )}
        {!standing.used_available && standing.note && (
          <span>{t('usage.rollingMinuteNote')}</span>
        )}
      </div>
    </div>
  );
}

/**
 * The Usage Policy visualization for the Team page.
 *
 * It reads the CURRENT period's limits and occupancy from
 * `GET /tenants/<id>/usage/quota` and adds no control of its own: U2 exposes
 * existing backend-supported limits only, and the editing surface stays where it
 * already lives.
 */
export function LimitStandingList({ quota }: { quota: IUsageEnvelope }) {
  const { t } = useTranslation();
  const data = quota.data as
    | {
        limits?: Record<string, number>;
        standing?: Record<string, IUsageLimitStanding>;
        zero_means_unlimited?: string[];
        limits_source?: string;
        limits_scope?: string;
        not_answered?: string;
        subject?: { live_member?: boolean; role?: string | null };
      }
    | undefined;

  const standing = data?.standing ?? {};
  const zeroMeansUnlimited = new Set(data?.zero_means_unlimited ?? []);
  const liveMemberFalse = data?.subject?.live_member === false;

  return (
    <div className="flex flex-col">
      <div className="flex flex-wrap items-baseline gap-2 pb-1">
        <span className="settings-section-hint">
          {data?.limits_source === 'backend_defaults'
            ? t('usage.limitsSourceDefaults')
            : t('usage.limitsSourceConfigured')}
        </span>
        <span className="settings-tag text-content-tertiary">
          {t('usage.limitsScopePerMember')}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-x-8 gap-y-3 lg:grid-cols-2">
        {DIMENSION_LABEL_KEYS.map(([dimension, labelKey]) => (
          <LimitRow
            key={dimension}
            dimension={dimension}
            labelKey={labelKey}
            standing={standing[dimension]}
          />
        ))}
      </div>

      {/* Which dimensions treat 0 as "not enforced" is a property of the rules,
          not of one row, so it is stated once instead of per dimension. */}
      {zeroMeansUnlimited.size > 0 && (
        <p className="settings-field-hint pt-2">
          {t('usage.zeroMeansNotEnforcedNote', {
            dimensions: Array.from(zeroMeansUnlimited)
              .map(
                (dimension) =>
                  DIMENSION_LABEL_KEYS.find(
                    ([key]) => key === dimension,
                  )?.[1] ?? dimension,
              )
              .map((labelKey) => t(labelKey))
              .join(', '),
          })}
        </p>
      )}

      {/* The semantics are the server's, but the WORDING is ours: the server's own
          caveat is English-only prose, and a Chinese console must not show an
          English paragraph. The statement below says the same things in the
          reader's language, so it is translatable and cannot drift into a
          different claim. */}
      <p className="settings-field-hint pt-2">
        {t('usage.limitsPerMemberCaveat')}
      </p>
      {liveMemberFalse && (
        <p className="settings-field-hint pt-1">
          {t('usage.memberNoLongerActive')}
        </p>
      )}
    </div>
  );
}
