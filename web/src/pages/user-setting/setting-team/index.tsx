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
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  useFetchTenantInfo,
  useFetchUserInfo,
} from '@/hooks/use-user-setting-request';
import { canRenderTenantControls } from '@/utils/tenant-role';
import { useTranslation } from 'react-i18next';

import {
  ceramicSearchFieldClassName,
  ceramicSearchFieldRootClassName,
} from '@/components/list-filter-bar';
import { SearchInput } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { UserPlus } from 'lucide-react';
import { useState } from 'react';
import { ProfileSettingWrapperCard } from '../components/user-setting-header';
import AddingUserModal from './add-user-modal';
import DepartmentTable from './department-table';
import { useAddUser } from './hooks';
import TenantTable from './tenant-table';
import UsagePolicySection from './usage-policy';
import UserTable from './user-table';

const UserSettingTeam = () => {
  const { data: userInfo } = useFetchUserInfo();
  // The active workspace's own record: `name` lives on the tenant, which is the
  // only place the workspace's name is reported (`GET /tenants` answers each
  // row with the OWNER's user row, so its `nickname` is a person, not a
  // workspace).
  const { data: tenantInfo } = useFetchTenantInfo();
  const { t } = useTranslation();
  const [searchTerm, setSearchTerm] = useState('');
  const [searchUser, setSearchUser] = useState('');
  // The workspace this page is showing, not the person reading it: a member who
  // owns no tenant of their own still works inside the one they joined. Controls
  // wait for the role to be reported, so a NORMAL member is never briefly offered
  // the invite button while `/users/me` is in flight.
  const readOnly = !canRenderTenantControls(userInfo?.role);
  /**
   * The header names the workspace. It must never fall back to the caller's own
   * nickname: a NORMAL member would then be told their personal space is this
   * page's subject while the workspace record is still in flight. An unknown
   * name renders the section label alone.
   */
  const workspaceName = tenantInfo?.name;
  const {
    addingTenantModalVisible,
    hideAddingTenantModal,
    showAddingTenantModal,
    handleAddUserOk,
    invitePath,
    loading,
  } = useAddUser();

  return (
    // <div className="w-full flex flex-col gap-4 relative">
    //   <Spotlight />
    //   <UserSettingHeader
    //     name={userInfo?.nickname + ' ' + t('setting.workspace')}
    //   />
    <ProfileSettingWrapperCard
      header={
        <header>
          <h2 className="text-2xl font-medium text-text-primary">
            {workspaceName
              ? `${workspaceName} ${t('setting.workspace')}`
              : t('setting.workspace')}
          </h2>
        </header>
      }
    >
      <div className="h-full overflow-x-hidden overflow-y-auto">
        <Card className="bg-transparent border-none rounded-none shadow-none">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 p-4">
            {/* <User className="mr-2 h-5 w-5 text-[#1677ff]" /> */}
            <CardTitle className="text-base">
              {t('setting.teamMembers')}
            </CardTitle>

            <section className="flex gap-4 items-center">
              <SearchInput
                className={cn(ceramicSearchFieldClassName, 'w-32')}
                rootClassName={cn(ceramicSearchFieldRootClassName)}
                placeholder={t('common.search')}
                value={searchUser}
                onChange={(e) => setSearchUser(e.target.value)}
              />
              {/* Only a workspace manager may change the roster. */}
              {!readOnly && (
                <Button
                  className="ceramic-cta h-8 shrink-0 rounded-[2px] px-3 text-xs font-medium gap-1.5 whitespace-nowrap"
                  onClick={showAddingTenantModal}
                >
                  <UserPlus className="size-3.5 shrink-0" />
                  {t('setting.invite')}
                </Button>
              )}
            </section>
          </CardHeader>

          <CardContent className="p-4 pt-0">
            <UserTable searchUser={searchUser}></UserTable>
          </CardContent>
        </Card>

        <Card className="bg-transparent border-none mt-8 rounded-none shadow-none">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 p-4">
            <CardTitle className="text-base w-fit">
              {t('setting.usagePolicy')}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            <UsagePolicySection readOnly={readOnly} />
          </CardContent>
        </Card>

        <Card className="bg-transparent border-none mt-8 rounded-none shadow-none">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 p-4">
            <CardTitle className="text-base w-fit">
              {t('setting.departments')}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            <DepartmentTable readOnly={readOnly} />
          </CardContent>
        </Card>

        <Card className="bg-transparent border-none mt-8 rounded-none shadow-none">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 p-4">
            <CardTitle className="text-base w-fit">
              {t('setting.joinedTeams')}
            </CardTitle>
            <SearchInput
              className={cn(ceramicSearchFieldClassName, 'w-32')}
              rootClassName={cn(ceramicSearchFieldRootClassName)}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder={t('common.search')}
            />
          </CardHeader>
          <CardContent className="p-4 pt-0">
            <TenantTable searchTerm={searchTerm}></TenantTable>
          </CardContent>
        </Card>
      </div>

      {addingTenantModalVisible && (
        <AddingUserModal
          visible
          hideModal={hideAddingTenantModal}
          onOk={handleAddUserOk}
          invitePath={invitePath}
          loading={loading}
        ></AddingUserModal>
      )}
    </ProfileSettingWrapperCard>
  );
};

export default UserSettingTeam;
