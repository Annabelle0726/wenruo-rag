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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useFetchUserInfo } from '@/hooks/use-user-setting-request';
import { canManageTenant } from '@/utils/tenant-role';
import { useTranslation } from 'react-i18next';
import { ProfileSettingWrapperCard } from '../components/user-setting-header';
import MyUsage from './my-usage';
import ProviderHealth from './provider-health';
import RetrievalHealth from './retrieval-health';
import WorkspaceAnalytics from './workspace-analytics';

/**
 * Usage & Operations.
 *
 * The four tabs are the console's observation surface, and the FIRST of them is
 * the only one a NORMAL member gets:
 *
 * - My Usage is every member's own view and reads their own rows;
 * - Workspace Analytics, Provider Health and Retrieval Health are operational
 *   views over the whole workspace, so they are rendered only for a role the
 *   server reports as OWNER or ADMIN.
 *
 * The gate WAITS for the role: while `/users/me` is in flight no administrative
 * tab is mounted, so a NORMAL member is never shown a tab whose first request the
 * server would refuse. This is a rendering decision only - the server is the
 * authority, and it re-checks the membership on every usage query regardless of
 * what the client renders.
 */
function UsageOperations() {
  const { t } = useTranslation();
  const { data: userInfo, loading } = useFetchUserInfo();
  const isManager = canManageTenant(userInfo?.role);

  return (
    <ProfileSettingWrapperCard
      header={
        <header className="flex flex-col gap-1">
          <h2 className="text-2xl font-medium text-text-primary">
            {t('setting.usageOperations')}
          </h2>
          <p className="text-xs text-text-secondary">
            {t('usage.pageDescription')}
          </p>
        </header>
      }
    >
      <Tabs defaultValue="my-usage" className="flex h-full flex-col">
        <TabsList className="shrink-0 px-4 pt-2">
          <TabsTrigger value="my-usage">{t('usage.tabMyUsage')}</TabsTrigger>
          {isManager && (
            <TabsTrigger value="workspace-analytics">
              {t('usage.tabWorkspaceAnalytics')}
            </TabsTrigger>
          )}
          {isManager && (
            <TabsTrigger value="provider-health">
              {t('usage.tabProviderHealth')}
            </TabsTrigger>
          )}
          {isManager && (
            <TabsTrigger value="retrieval-health">
              {t('usage.tabRetrievalHealth')}
            </TabsTrigger>
          )}
        </TabsList>

        {loading && !userInfo?.role ? (
          <div className="p-4">
            <CardSkeleton />
          </div>
        ) : (
          <>
            <TabsContent value="my-usage" className="min-h-0 flex-1">
              <MyUsage />
            </TabsContent>

            {isManager && (
              <TabsContent value="workspace-analytics" className="min-h-0 flex-1">
                <WorkspaceAnalytics />
              </TabsContent>
            )}

            {isManager && (
              <TabsContent value="provider-health" className="min-h-0 flex-1">
                <ProviderHealth />
              </TabsContent>
            )}

            {isManager && (
              <TabsContent value="retrieval-health" className="min-h-0 flex-1">
                <RetrievalHealth />
              </TabsContent>
            )}
          </>
        )}
      </Tabs>
    </ProfileSettingWrapperCard>
  );
}

export default UsageOperations;
