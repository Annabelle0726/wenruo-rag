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
import { useFetchQuotaStatus } from '@/hooks/use-workspace-usage-request';
import { useTranslation } from 'react-i18next';
import { ComingDataPanel } from '../usage-operations/components/coming-data-panel';
import { LimitStandingList } from '../usage-operations/components/limit-standing-list';
import { ReadModelNotice } from '../usage-operations/components/read-model-notice';

/**
 * Team > Usage policy: the workspace's limits, VISUALIZED.
 *
 * This is a destination of its own, and it is read-only: the round exposes the
 * limits the backend already supports for display and adds no limit, no control
 * and no write path of its own. The numbers come straight from
 * `GET /tenants/<id>/usage/quota`, so the three states are the server's:
 *
 * - a limit of 0 means the dimension is NOT ENFORCED (never "zero remaining");
 * - an exempt OWNER/ADMIN sees the exemption instead of a bar they cannot fail;
 * - an absent budget row means the BACKEND DEFAULTS apply, and the view says so
 *   rather than implying someone configured these numbers.
 *
 * A NORMAL member has no workspace limit view: their own standing is in Usage &
 * Operations > My usage. The rail does not offer this destination to them, and a
 * direct visit renders the not-authorized state instead of a request the server
 * would refuse.
 */
export function UsagePolicySection({
  readOnly,
  roleResolved = true,
}: {
  readOnly: boolean;
  roleResolved?: boolean;
}) {
  const { t } = useTranslation();
  const { data: quota, loading, refetch, error } = useFetchQuotaStatus();

  if (!roleResolved) {
    return (
      <div className="p-4">
        <CardSkeleton />
      </div>
    );
  }

  if (readOnly) {
    return (
      <div className="p-4">
        <ComingDataPanel
          testId="usage-policy-not-authorized"
          tone="unavailable"
          titleKey="usage.subsectionNotAuthorizedTitle"
          descriptionKey="usage.subsectionNotAuthorizedDescription"
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 p-4" data-testid="team-usage-policy">
      <div className="flex flex-col gap-1">
        <h3 className="text-sm text-text-primary">
          {t('usage.policyTitle')}
        </h3>
        <p className="text-xs text-text-secondary">
          {t('usage.policyDescription')}
        </p>
      </div>

      {loading && !quota ? (
        <CardSkeleton />
      ) : quota?.data ? (
        <LimitStandingList quota={quota} />
      ) : (
        <ReadModelNotice
          testId="usage-policy-unavailable"
          failed={Boolean(error)}
          onRetry={refetch}
        />
      )}
    </div>
  );
}

export default UsagePolicySection;
