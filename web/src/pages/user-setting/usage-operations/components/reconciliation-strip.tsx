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

import { IUsageEnvelope } from '@/interfaces/database/workspace-usage';
import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';

/**
 * The reconciliation strip.
 *
 * The counters and the ledger are two records of the same attempts and nothing
 * reconciles them automatically, so a disagreement is TOLD to the reader rather
 * than resolved by showing whichever figure looks better. Both numbers are on
 * screen either way.
 *
 * It renders the payload's OWN `reconciliation` block and computes nothing: the
 * workspace reads, the member's own read and the member report all carry one, and
 * none of them is summed here.
 */
export function ReconciliationStrip({
  payload,
  testId = 'usage-reconciliation',
}: {
  payload: IUsageEnvelope;
  testId?: string;
}) {
  const { t } = useTranslation();
  const reconciliation = payload.reconciliation;

  if (!reconciliation) {
    return null;
  }

  const consistent =
    reconciliation.calls_consistent && reconciliation.tokens_consistent;

  return (
    <div className="settings-tile" data-testid={testId}>
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

export default ReconciliationStrip;
