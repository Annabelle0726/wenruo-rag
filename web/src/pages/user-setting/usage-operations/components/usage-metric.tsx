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

import { CostCoverage } from '@/interfaces/database/workspace-usage';
import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';
import { formatCount, resolveCostDisplay } from './usage-format';

export function UsageMetricGrid({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4',
        className,
      )}
    >
      {children}
    </div>
  );
}

export function UsageMetricTile({
  label,
  value,
  hint,
  tone = 'default',
  testId,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: 'default' | 'outstanding';
  testId?: string;
}) {
  return (
    <div className="settings-tile" data-testid={testId}>
      <span className="settings-tile-label">{label}</span>
      <span
        className={cn(
          'settings-tile-value',
          tone === 'outstanding' && 'text-state-warning',
        )}
      >
        {value}
      </span>
      {hint && <span className="settings-tile-hint">{hint}</span>}
    </div>
  );
}

/**
 * A cost figure, rendered through the "not established means not available" rule.
 *
 * `$0.00` is never produced from a missing price: an unpriced scope shows the
 * "Not available" copy, and a scope where only some rows carry pricing is
 * labelled `Partial` next to the real sum.
 */
export function EstimatedCostTile({
  label,
  micros,
  coverage,
  testId,
}: {
  label: string;
  micros: number | null | undefined;
  coverage: CostCoverage | undefined;
  testId?: string;
}) {
  const { t } = useTranslation();
  const display = resolveCostDisplay(micros, coverage);

  return (
    <UsageMetricTile
      label={label}
      testId={testId}
      value={
        display.kind === 'unavailable' ? (
          <span className="text-base font-medium text-text-disabled">
            {t('usage.costNotAvailable')}
          </span>
        ) : (
          <span className="flex items-baseline gap-1.5">
            {display.usd}
            {display.kind === 'partial' && (
              <span className="text-xs font-medium text-state-warning">
                {t('usage.costPartial')}
              </span>
            )}
          </span>
        )
      }
      hint={t('usage.estimatedCostHint', {
        coverage: t(
          display.kind === 'unavailable'
            ? 'usage.coverageUnavailable'
            : display.kind === 'partial'
              ? 'usage.coveragePartial'
              : 'usage.coverageComplete',
        ),
      })}
    />
  );
}

/** Calls and tokens: the two figures the read model always has. */
export function UsageTotalsGrid({
  attemptedCalls,
  settledTokens,
  outstandingTokens,
  effectiveTokens,
}: {
  attemptedCalls: number;
  settledTokens: number;
  outstandingTokens: number;
  effectiveTokens: number;
}) {
  const { t } = useTranslation();

  return (
    <UsageMetricGrid>
      <UsageMetricTile
        label={t('usage.attemptedCalls')}
        value={formatCount(attemptedCalls)}
        hint={t('usage.attemptedCallsHint')}
        testId="usage-attempted-calls"
      />
      <UsageMetricTile
        label={t('usage.settledTokens')}
        value={formatCount(settledTokens)}
        testId="usage-settled-tokens"
      />
      <UsageMetricTile
        label={t('usage.outstandingTokens')}
        value={formatCount(outstandingTokens)}
        hint={t('usage.outstandingTokensHint')}
        tone="outstanding"
        testId="usage-outstanding-tokens"
      />
      <UsageMetricTile
        label={t('usage.effectiveTokens')}
        value={formatCount(effectiveTokens)}
        hint={t('usage.effectiveTokensHint')}
        testId="usage-effective-tokens"
      />
    </UsageMetricGrid>
  );
}
