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

import { useTranslation } from 'react-i18next';
import { ComingDataPanel } from './components/coming-data-panel';

/**
 * Provider Health - an HONEST EMPTY STATE, and nothing else.
 *
 * There is no backend provider-health fact model yet, so this view has no values
 * to show and shows none. Concretely, it renders:
 *
 * - no status word (`Healthy` / `Degraded` / `Unavailable`) for any provider,
 *   because no observation exists to base one on;
 * - no latency, error rate or consecutive-failure count;
 * - no provider balance, remaining quota or usage figure - a private/self-hosted
 *   endpoint exposes no such concept at all, and no provider adapter exists to
 *   read one from a managed provider;
 * - no fallback claim, because "the system switched to lexical" is a Retrieval
 *   Health fact that this layer must never infer.
 *
 * The panel names what is missing instead of filling the space with a mock.
 */
function ProviderHealth() {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col gap-4 p-4">
      <h3 className="text-sm text-text-primary">{t('usage.providerHealth')}</h3>

      <ComingDataPanel
        testId="provider-health-coming-data"
        tone="unavailable"
        titleKey="usage.providerHealthEmptyTitle"
        descriptionKey="usage.providerHealthEmptyDescription"
        pendingKeys={[
          'usage.providerHealthPendingObservation',
          'usage.providerHealthPendingFailureClass',
          'usage.providerHealthPendingCapability',
        ]}
      />

      <div className="ceramic-relief flex flex-col gap-1 rounded-[2px] p-3">
        <span className="text-xs text-text-secondary">
          {t('usage.providerHealthNotShownTitle')}
        </span>
        <ul className="flex flex-col gap-1 ps-4 text-xs text-text-disabled">
          <li className="list-disc">
            {t('usage.providerHealthNotShownStatus')}
          </li>
          <li className="list-disc">
            {t('usage.providerHealthNotShownBalance')}
          </li>
          <li className="list-disc">
            {t('usage.providerHealthNotShownFallback')}
          </li>
        </ul>
      </div>
    </div>
  );
}

export default ProviderHealth;
