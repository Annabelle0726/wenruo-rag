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

import { Button } from '@/components/ui/button';
import { CardSkeleton } from '@/components/ui/skeleton';
import {
  ProviderHealthErrorKind,
  useFetchProviderIncidents,
} from '@/hooks/use-provider-health-request';
import { LucideCircleDashed } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { activeIncidentsOf, resolvedIncidentsOf } from '@/utils/provider-incident';
import { ProviderIncidentList } from './components/provider-incident-list';

/**
 * Provider Health - the incidents the observation path actually recorded.
 *
 * FIVE states, and the difference between two of them is the whole point:
 *
 * - **idle**: the workspace is not resolved yet, so nothing has been read. This is
 *   NOT an empty answer and does not claim one;
 * - **loading**: a read is in flight;
 * - **success**: incidents, or the honest empty state when the server answered
 *   with none;
 * - **empty**: "no provider health fact has been recorded yet". It never says the
 *   services are healthy - nothing here polls a provider, and an absence of
 *   incidents is an absence of incidents;
 * - **error**: the read was refused or failed. A refusal is reported as a refusal
 *   and cannot be retried into success; a failure offers a retry. Neither is ever
 *   rendered as "no incidents", which is the confusion this page exists to avoid.
 *
 * The numbers on screen are the server's: the counts are exact for the workspace,
 * `severity`, `error_class` and the sentences come from the same response, and the
 * recently-resolved window is the server's own bound (stated below rather than
 * implied). Nothing here reclassifies a failure, sums occurrences or polls.
 */
function ProviderHealth() {
  const { t } = useTranslation();
  const { data, loading, idle, error, refetch } = useFetchProviderIncidents();

  const active = activeIncidentsOf(data);
  const resolved = resolvedIncidentsOf(data);
  const refused = error?.kind === ProviderHealthErrorKind.Refused;

  const renderBody = () => {
    if (idle) {
      return (
        <div className="settings-notice" data-testid="provider-health-idle">
          <LucideCircleDashed className="mt-0.5 size-4 shrink-0 text-text-disabled" />
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <p className="settings-notice-title">
              {t('usage.providerHealthIdleTitle')}
            </p>
            <p className="settings-notice-body">
              {t('usage.providerHealthIdleDescription')}
            </p>
          </div>
        </div>
      );
    }

    if (loading && !data) {
      return (
        <div data-testid="provider-health-loading">
          <CardSkeleton />
        </div>
      );
    }

    // An error is never an empty answer: it is reported as its own state, with
    // the reason. A refusal offers no retry, because retrying cannot succeed.
    if (error) {
      return (
        <div className="settings-notice" data-testid="provider-health-error">
          <LucideCircleDashed className="mt-0.5 size-4 shrink-0 text-state-error" />
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <p className="settings-notice-title">
              {t(
                refused
                  ? 'usage.providerHealthRefusedTitle'
                  : 'usage.providerHealthErrorTitle',
              )}
            </p>
            <p className="settings-notice-body">
              {t(
                refused
                  ? 'usage.providerHealthRefusedDescription'
                  : 'usage.providerHealthErrorDescription',
              )}
            </p>
            {!refused && (
              <div className="pt-1">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 px-3 text-xs"
                  onClick={() => void refetch()}
                >
                  {t('common.retry')}
                </Button>
              </div>
            )}
          </div>
        </div>
      );
    }

    if (active.length === 0 && resolved.length === 0) {
      return (
        <div className="settings-notice" data-testid="provider-health-empty">
          <LucideCircleDashed className="mt-0.5 size-4 shrink-0 text-text-disabled" />
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <p className="settings-notice-title">
              {t('usage.providerHealthEmptyTitle')}
            </p>
            <p className="settings-notice-body">
              {t('usage.providerHealthEmptyDescription')}
            </p>
          </div>
        </div>
      );
    }

    return (
      <div data-testid="provider-health-ready">
        <ProviderIncidentList active={active} resolved={resolved} />
        <p className="pt-2 text-xs text-text-tertiary">
          {t('usage.providerHealthResolvedWindow', {
            days: data?.recently_resolved_window_days ?? 0,
          })}
        </p>
      </div>
    );
  };

  return (
    <div className="settings-body">
      {renderBody()}

      {/* Still true, and the reason this page carries no green light. */}
      <div className="settings-tile">
        <span className="settings-tile-label">
          {t('usage.providerHealthNotShownTitle')}
        </span>
        <ul className="flex flex-col gap-1 ps-4 text-xs text-content-tertiary">
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
