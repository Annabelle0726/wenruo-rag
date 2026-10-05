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

import { CardIdentityIcon } from '@/components/card-identity-icon';
import { SearchHighlight } from '@/components/search-highlight';
import RoleTag from '@/components/role-tag';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  useFetchUserInfo,
  useListTenant,
  useSetActiveTenant,
} from '@/hooks/use-user-setting-request';
import { formatDate } from '@/utils/date';
import { ArrowDown, ArrowUp, ArrowUpDown, LogOut } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { TenantRole } from '../constants';
import EmptyTableRow from './empty-table-row';
import { useHandleAgreeTenant, useHandleQuitUser } from './hooks';

/**
 * Every workspace the caller belongs to, with the active one flagged and a
 * control to switch to any other.
 *
 * Switching is what makes the rest of the app change workspace: the server
 * persists the selection and the request interceptor sends it as
 * `X-Tenant-Id` from then on.
 */
const TenantTable = ({ searchTerm }: { searchTerm: string }) => {
  const { t } = useTranslation();
  const { data, loading } = useListTenant();
  const { handleAgree } = useHandleAgreeTenant();
  const { setActiveTenant, loading: switching } = useSetActiveTenant();
  const { data: user } = useFetchUserInfo();
  const { handleQuitTenantUser } = useHandleQuitUser();
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc' | null>(null);
  const sortedData = useMemo(() => {
    if (!data || data.length === 0) return data;
    let filtered = data;
    if (searchTerm) {
      filtered = data.filter(
        (tenant) =>
          (tenant.name ?? '')
            .toLowerCase()
            .includes(searchTerm.toLowerCase()) ||
          tenant.nickname.toLowerCase().includes(searchTerm.toLowerCase()) ||
          tenant.email.toLowerCase().includes(searchTerm.toLowerCase()),
      );
    }
    if (sortOrder) {
      filtered = [...filtered].sort((a, b) => {
        const dateA = new Date(a.update_date).getTime();
        const dateB = new Date(b.update_date).getTime();

        if (sortOrder === 'asc') {
          return dateA - dateB;
        } else {
          return dateB - dateA;
        }
      });
    }

    return filtered;
  }, [data, sortOrder, searchTerm]);

  const toggleSortOrder = () => {
    if (sortOrder === 'asc') {
      setSortOrder('desc');
    } else if (sortOrder === 'desc') {
      setSortOrder(null);
    } else {
      setSortOrder('asc');
    }
  };

  const renderSortIcon = () => {
    if (sortOrder === 'asc') {
      return <ArrowUp className="size-[1em]" />;
    } else if (sortOrder === 'desc') {
      return <ArrowDown className="size-[1em]" />;
    } else {
      return <ArrowUpDown className="size-[1em]" />;
    }
  };

  return (
    <Table
      rootClassName="settings-table [&_td]:py-0 [&_th]:py-0 [&_th]:whitespace-nowrap"
      className="table-fixed [&_td]:overflow-hidden"
    >
      <TableHeader className="bg-table-header">
        <TableRow className="border-b border-table-border hover:bg-table-header">
          <TableHead className="settings-table-head-cell">
            {t('common.name')}
          </TableHead>
          <TableHead className="settings-table-head-cell">
            <div className="flex items-center gap-1">
              {t('setting.updateDate')}
              <Button
                variant="ghost"
                size="icon-xs"
                onClick={toggleSortOrder}
                aria-label={t('setting.updateDate')}
              >
                {renderSortIcon()}
              </Button>
            </div>
          </TableHead>
          <TableHead className="settings-table-head-cell">
            {t('setting.email')}
          </TableHead>
          <TableHead className="settings-table-head-cell">
            {t('setting.role')}
          </TableHead>
          <TableHead className="settings-table-head-cell">
            {t('common.action')}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {loading ? (
          <TableRow className="settings-table-row border-0 hover:bg-transparent">
            <TableCell colSpan={5} className="settings-table-cell">
              <div className="flex items-center justify-center py-6">
                <div className="size-4 animate-spin rounded-[50%] border-2 border-solid border-content-tertiary border-r-transparent motion-reduce:animate-[spin_1.5s_linear_infinite]"></div>
              </div>
            </TableCell>
          </TableRow>
        ) : sortedData && sortedData.length > 0 ? (
          sortedData.map((tenant) => (
            <TableRow key={tenant.tenant_id} className="settings-table-row">
              <TableCell className="settings-table-cell">
                <div className="flex items-center gap-1.5">
                  {/* The workspace's own name, and the owner's mark beside it:
                      the row names a TEAM, so the owner's nickname is only the
                      fallback for a payload that carries no name. */}
                  <CardIdentityIcon
                    kind="user"
                    avatar={tenant.avatar}
                    className="size-4"
                    iconClassName="size-3"
                  />
                  <span className="truncate">
                    <SearchHighlight
                      text={tenant.name || tenant.nickname}
                      query={searchTerm}
                    />
                  </span>
                </div>
              </TableCell>
              <TableCell className="settings-table-cell font-mono text-xs text-content-secondary">
                {formatDate(tenant.update_date)}
              </TableCell>
              <TableCell className="settings-table-cell text-content-secondary">
                <span className="block truncate">
                  <SearchHighlight text={tenant.email} query={searchTerm} />
                </span>
              </TableCell>
              <TableCell className="settings-table-cell">
                <RoleTag role={tenant.role} />
              </TableCell>
              <TableCell className="settings-table-cell">
                {tenant.role === TenantRole.Invite ? (
                  <div className="flex items-center gap-3">
                    <Button
                      variant="link"
                      className="h-8 p-0 text-xs"
                      onClick={handleAgree(tenant.tenant_id, true)}
                    >
                      {t(`setting.agree`)}
                    </Button>
                    <Button
                      variant="link"
                      className="h-8 p-0 text-xs"
                      onClick={handleAgree(tenant.tenant_id, false)}
                    >
                      {t(`setting.refuse`)}
                    </Button>
                  </div>
                ) : (
                  <div className="flex items-center justify-end gap-3">
                    {tenant.is_active ? (
                      <span className="settings-tag border-status-available-border text-status-available-ink">
                        {t('setting.currentWorkspace')}
                      </span>
                    ) : (
                      <Button
                        variant="link"
                        className="h-8 p-0 text-xs"
                        disabled={switching}
                        onClick={() => setActiveTenant(tenant.tenant_id)}
                      >
                        {t('setting.switchWorkspace')}
                      </Button>
                    )}
                    {/*
                      Leaving is offered on the workspace you are in as well as
                      on the others - otherwise a member could never quit the
                      one they are stuck in - but never on a workspace the
                      caller owns, which the server refuses to remove.
                    */}
                    {tenant.role === TenantRole.Owner ? null : (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-8 p-0 text-content-tertiary hover:text-text-primary"
                        aria-label={t('setting.quit')}
                        disabled={!user?.id}
                        onClick={handleQuitTenantUser(
                          user?.id,
                          tenant.tenant_id,
                        )}
                      >
                        <LogOut className="size-4" />
                      </Button>
                    )}
                  </div>
                )}
              </TableCell>
            </TableRow>
          ))
        ) : (
          <EmptyTableRow colSpan={5} label={t('common.noData')} />
        )}
      </TableBody>
    </Table>
  );
};

export default TenantTable;
