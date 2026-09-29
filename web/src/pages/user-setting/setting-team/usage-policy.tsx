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

/**
 * The Team page's Usage Policy: the workspace's limits, VISUALIZED.
 *
 * This is deliberately read-only. U2 exposes existing backend-supported limits
 * for display; it adds no limit of its own and no editing surface, and the pages
 * here may only read the frozen GET endpoints. The numbers come straight from
 * `GET /tenants/<id>/usage/quota`, so the three states are the server's:
 *
 * - a limit of 0 means the dimension is NOT ENFORCED (never "zero remaining");
 * - an exempt OWNER/ADMIN sees the exemption rather than a bar they cannot fail;
 * - an absent budget row means the BACKEND DEFAULTS apply, and the view says so
 *   instead of implying someone configured these numbers.
 */
export function UsagePolicySection({ readOnly }: { readOnly: boolean }) {
  const { t } = useTranslation();
  const { data: quota, loading } = useFetchQuotaStatus();

  // A NORMAL member has no limits to administer and no workspace limit view: their
  // own standing is shown in Usage & Operations > My Usage instead.
  if (readOnly) {
    return null;
  }

  return (
    <div
      className="flex flex-col gap-2"
      data-testid="team-usage-policy"
    >
      <p className="text-xs text-text-secondary">
        {t('usage.policyDescription')}
      </p>

      {loading && !quota ? (
        <CardSkeleton />
      ) : quota?.data ? (
        <LimitStandingList quota={quota} />
      ) : (
        <ComingDataPanel
          testId="usage-policy-unavailable"
          tone="unavailable"
          titleKey="usage.unavailableTitle"
          descriptionKey="usage.quotaUnavailableDescription"
        />
      )}
    </div>
  );
}

export default UsagePolicySection;
