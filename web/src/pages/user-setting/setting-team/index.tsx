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
  useFetchTenantInfo,
  useFetchUserInfo,
} from '@/hooks/use-user-setting-request';
import { canRenderTenantControls } from '@/utils/tenant-role';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation } from 'react-router';

import {
  ceramicSearchFieldClassName,
  ceramicSearchFieldRootClassName,
} from '@/components/list-filter-bar';
import { Button } from '@/components/ui/button';
import { SearchInput } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { ProfileSettingWrapperCard } from '../components/user-setting-header';
import AddingUserModal from './add-user-modal';
import DepartmentTable from './department-table';
import { useAddUser } from './hooks';
import TenantTable from './tenant-table';
import UsagePolicySection from './usage-policy';
import UserTable from './user-table';

/**
 * The Team section's subsections.
 *
 * Members & roles, Usage policy and Department management are separate
 * DESTINATIONS - the route names one and the page renders it - rather than three
 * cards stacked on one page. The previous shape put Usage policy at the bottom of
 * the roster, where it read as an afterthought and could not be linked to.
 */
const SUBSECTIONS = ['members', 'usage-policy', 'departments'] as const;

type TeamSubsection = (typeof SUBSECTIONS)[number];

const SUBSECTION_TITLE_KEY: Record<TeamSubsection, string> = {
  members: 'setting.teamMembersAndRoles',
  'usage-policy': 'setting.usagePolicy',
  departments: 'setting.teamDepartments',
};

const resolveSubsection = (pathname: string): TeamSubsection => {
  const segment = pathname.split('/').filter(Boolean).pop() ?? '';
  return (SUBSECTIONS as readonly string[]).includes(segment)
    ? (segment as TeamSubsection)
    : 'members';
};

const UserSettingTeam = () => {
  const { data: userInfo } = useFetchUserInfo();
  // The active workspace's own record: `name` lives on the tenant, which is the
  // only place the workspace's name is reported.
  const { data: tenantInfo } = useFetchTenantInfo();
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const [searchTerm, setSearchTerm] = useState('');
  const [searchUser, setSearchUser] = useState('');
  const subsection = useMemo(() => resolveSubsection(pathname), [pathname]);
  // Controls wait for the role to be reported, so a NORMAL member is never
  // briefly offered the invite button while `/users/me` is in flight.
  const readOnly = !canRenderTenantControls(userInfo?.role);
  const roleResolved = Boolean(userInfo?.role);
  /**
   * The header names the workspace. It must never fall back to the caller's own
   * nickname: a NORMAL member would then be told their personal space is this
   * page's subject while the workspace record is still in flight.
   */
  const workspaceName = tenantInfo?.name;
  const {
    addingTenantModalVisible,
    hideAddingTenantModal,
    showAddingTenantModal,
    handleAddUserOk,
    invitePath,
    loading: inviting,
  } = useAddUser();

  const renderSubsection = () => {
    if (subsection === 'usage-policy') {
      return (
        <UsagePolicySection readOnly={readOnly} roleResolved={roleResolved} />
      );
    }

    if (subsection === 'departments') {
      return (
        <div className="settings-body">
          <section className="settings-section">
            <div className="settings-section-head">
              <h3 className="settings-section-title">
                {t('setting.teamDepartments')}
              </h3>
            </div>
            <div className="settings-section-body">
              <DepartmentTable readOnly={readOnly} />
            </div>
          </section>
        </div>
      );
    }

    return (
      <div className="settings-body">
        <section className="settings-section" data-testid="members-section">
          <div className="settings-section-head">
            <h3 className="settings-section-title">
              {t('setting.teamMembers')}
            </h3>

            <div className="ms-auto flex items-center gap-2">
              <SearchInput
                className={cn(ceramicSearchFieldClassName, 'w-40')}
                rootClassName={cn(ceramicSearchFieldRootClassName)}
                placeholder={t('common.search')}
                value={searchUser}
                onChange={(e) => setSearchUser(e.target.value)}
              />
              {/* Only a workspace manager may change the roster. */}
              {!readOnly && (
                <Button
                  className="ceramic-cta h-8 shrink-0 gap-1.5 whitespace-nowrap px-3 text-xs font-medium"
                  onClick={showAddingTenantModal}
                >
                  {t('setting.invite')}
                </Button>
              )}
            </div>
          </div>

          <UserTable searchUser={searchUser} />
        </section>

        {/* The workspaces the caller belongs to. It stays under Members & roles
            because it is the same roster question read from the other side. */}
        <section className="settings-section" data-testid="joined-workspaces-section">
          <div className="settings-section-head">
            <h3 className="settings-section-title">
              {t('setting.joinedTeams')}
            </h3>
            <SearchInput
              className={cn(ceramicSearchFieldClassName, 'ms-auto w-40')}
              rootClassName={cn(ceramicSearchFieldRootClassName)}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder={t('common.search')}
            />
          </div>
          <TenantTable searchTerm={searchTerm} />
        </section>
      </div>
    );
  };

  return (
    <ProfileSettingWrapperCard
      header={
        <header className="flex min-w-0 flex-col gap-0.5">
          <h2 className="settings-title truncate">
            {t(SUBSECTION_TITLE_KEY[subsection])}
          </h2>
          <p className="settings-description truncate">
            {workspaceName
              ? `${workspaceName} ${t('setting.workspace')}`
              : t('setting.workspace')}
          </p>
        </header>
      }
    >
      {renderSubsection()}

      {addingTenantModalVisible && (
        <AddingUserModal
          visible
          hideModal={hideAddingTenantModal}
          onOk={handleAddUserOk}
          invitePath={invitePath}
          loading={inviting}
        />
      )}
    </ProfileSettingWrapperCard>
  );
};

export default UserSettingTeam;
