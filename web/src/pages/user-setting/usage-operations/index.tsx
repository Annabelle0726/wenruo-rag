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
import { useFetchUserInfo } from '@/hooks/use-user-setting-request';
import { canManageTenant } from '@/utils/tenant-role';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation } from 'react-router';
import { ProfileSettingWrapperCard } from '../components/user-setting-header';
import { ComingDataPanel } from './components/coming-data-panel';
import MyUsage from './my-usage';
import ProviderHealth from './provider-health';
import RetrievalHealth from './retrieval-health';
import WorkspaceAnalytics from './workspace-analytics';

/**
 * The Usage & Operations subsection the route names.
 *
 * The subsection comes from the URL, not from component state, so the rail's
 * active child, the breadcrumb and the rendered destination are the same piece of
 * information. A path with no subsection lands on My Usage, which is the one
 * destination every member has.
 */
const SUBSECTIONS = ['my', 'workspace', 'provider-health', 'retrieval-health'] as const;

type UsageSubsection = (typeof SUBSECTIONS)[number];

const ADMIN_ONLY: ReadonlySet<UsageSubsection> = new Set([
  'workspace',
  'provider-health',
  'retrieval-health',
]);

const SUBSECTION_TITLE_KEY: Record<UsageSubsection, string> = {
  my: 'usage.myUsage',
  workspace: 'usage.workspaceAnalytics',
  'provider-health': 'usage.providerHealth',
  'retrieval-health': 'usage.retrievalHealth',
};

const resolveSubsection = (pathname: string): UsageSubsection => {
  const segment = pathname.split('/').filter(Boolean).pop() ?? '';
  return (SUBSECTIONS as readonly string[]).includes(segment)
    ? (segment as UsageSubsection)
    : 'my';
};

/**
 * Usage & Operations: one destination per subsection, all four of them reached
 * from the Settings rail's second level.
 *
 * There is no horizontal tab strip any more. Two navigation surfaces for the same
 * four destinations is what made this section look flat and, worse, let the two
 * disagree: the rail could highlight "Provider Health" while a tab strip showed
 * "My Usage" as selected.
 *
 * The administrative subsections are not rendered until the role is known, and a
 * NORMAL member never gets them: their component (and therefore its queries) is
 * not mounted at all, so no refused request is ever sent. This is a rendering
 * decision, NOT the authorization boundary - the server re-checks the live
 * membership on every usage query regardless of what the client renders.
 */
function UsageOperations() {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const { data: userInfo, loading } = useFetchUserInfo();
  const isManager = canManageTenant(userInfo?.role);
  const subsection = useMemo(() => resolveSubsection(pathname), [pathname]);
  const roleResolved = Boolean(userInfo?.role);

  const renderSubsection = () => {
    if (ADMIN_ONLY.has(subsection) && !isManager) {
      return (
        <div className="p-4">
          <ComingDataPanel
            testId="usage-subsection-not-authorized"
            tone="unavailable"
            titleKey="usage.subsectionNotAuthorizedTitle"
            descriptionKey="usage.subsectionNotAuthorizedDescription"
          />
        </div>
      );
    }

    switch (subsection) {
      case 'workspace':
        return <WorkspaceAnalytics />;
      case 'provider-health':
        return <ProviderHealth />;
      case 'retrieval-health':
        return <RetrievalHealth />;
      default:
        return <MyUsage />;
    }
  };

  return (
    <ProfileSettingWrapperCard
      header={
        <header className="flex flex-col gap-1">
          <h2 className="text-2xl font-medium text-text-primary">
            {t(SUBSECTION_TITLE_KEY[subsection])}
          </h2>
          <p className="text-xs text-text-secondary">
            {t('usage.pageDescription')}
          </p>
        </header>
      }
    >
      {/* The role decides which subsections exist, so the body waits for it
          instead of rendering an administrative view that a member would only see
          replaced. */}
      {loading && !roleResolved ? (
        <div className="p-4">
          <CardSkeleton />
        </div>
      ) : (
        renderSubsection()
      )}
    </ProfileSettingWrapperCard>
  );
}

export default UsageOperations;
