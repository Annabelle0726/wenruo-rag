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
  ConfirmDeleteDialog,
  ConfirmDeleteDialogNode,
} from '@/components/confirm-delete-dialog';
import { CardIdentityIcon } from '@/components/card-identity-icon';
import RoleTag from '@/components/role-tag';
import { SearchHighlight } from '@/components/search-highlight';
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
  useListDepartments,
  useListTenantUser,
  useFetchUserInfo,
  useUpdateTenantUserProfile,
  useUpdateTenantUserRole,
} from '@/hooks/use-user-setting-request';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  canRenderTenantControls,
  isAssignableTenantRole,
} from '@/utils/tenant-role';
import { formatDate } from '@/utils/date';
import { ArrowDown, ArrowUp, ArrowUpDown, Trash2 } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { TenantRole } from '../constants';
import DepartmentSelect from './department-select';
import EmptyTableRow from './empty-table-row';
import { useHandleDeleteUser } from './hooks';

/** Sentinel for "no filter": a Select value cannot be an empty string. */
const ALL_DEPARTMENTS = '__all__';

const UserTable = ({ searchUser }: { searchUser: string }) => {
  const { data, loading } = useListTenantUser();
  const { data: userInfo } = useFetchUserInfo();
  const { deleteTenantUser } = useHandleDeleteUser();
  // Only a workspace manager may change the roster, and the owner is never
  // removable. Showing the control to anyone else invites a click that the
  // server refuses with 108 â€?including the window before `/users/me` reports the
  // caller's role, which is why the controls wait for a known one.
  const readOnly = !canRenderTenantControls(userInfo?.role);
  const { updateTenantUserRole } = useUpdateTenantUserRole();
  const { updateTenantUserProfile } = useUpdateTenantUserProfile();
  const { data: departments } = useListDepartments();
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc' | null>(null);
  const [departmentFilter, setDepartmentFilter] = useState('');
  const { t } = useTranslation();
  const sortedData = useMemo(() => {
    if (!data || data.length === 0) return data;
    let filtered = data;
    if (departmentFilter) {
      filtered = filtered.filter(
        (member) => member.department_id === departmentFilter,
      );
    }
    if (searchUser) {
      filtered = filtered.filter(
        (tenant) =>
          tenant.nickname.toLowerCase().includes(searchUser.toLowerCase()) ||
          tenant.email.toLowerCase().includes(searchUser.toLowerCase()),
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
  }, [data, sortOrder, searchUser, departmentFilter]);
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
      return <ArrowUp className="size-[1em] " />;
    } else if (sortOrder === 'desc') {
      return <ArrowDown className="size-[1em]" />;
    } else {
      return <ArrowUpDown className="size-[1em]" />;
    }
  };
  return (
    <div>
      {/* The filter row belongs to the table, not to a card around it: it sits on
          the table's own top edge, so "these rows, filtered this way" is one
          object instead of a framed control above a framed table. */}
      <div className="settings-table-toolbar">
        <label className="flex items-center gap-2">
          <span className="settings-field-label">
            {t('setting.department')}
          </span>
          <Select
            value={departmentFilter || undefined}
            onValueChange={(value) =>
              setDepartmentFilter(value === ALL_DEPARTMENTS ? '' : value)
            }
          >
            <SelectTrigger
              className="ceramic-field h-8 w-40"
              data-testid="department-filter"
            >
              <SelectValue placeholder={t('setting.allDepartments')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_DEPARTMENTS}>
                {t('setting.allDepartments')}
              </SelectItem>
              {departments.map((department) => (
                <SelectItem key={department.id} value={department.id}>
                  {department.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
      </div>
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
              {t('setting.department')}
            </TableHead>
            <TableHead className="settings-table-head-cell">
              {t('setting.title')}
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
              <TableCell colSpan={7} className="settings-table-cell">
                <div className="flex items-center justify-center py-6">
                  <div className="size-4 animate-spin rounded-[50%] border-2 border-solid border-content-tertiary border-r-transparent motion-reduce:animate-[spin_1.5s_linear_infinite]"></div>
                </div>
              </TableCell>
            </TableRow>
          ) : sortedData && sortedData.length > 0 ? (
            sortedData.map((record) => (
              <TableRow
                key={record.user_id}
                className="settings-table-row"
              >
                <TableCell className="settings-table-cell">
                  <div className="flex items-center gap-1.5">
                    {/* A person's mark, never the first letter of the nickname:
                        the name is printed right beside it. */}
                    <CardIdentityIcon
                      kind="user"
                      avatar={record.avatar}
                      className="size-4"
                      iconClassName="size-3"
                    />
                    <span className="truncate">
                      <SearchHighlight
                        text={record.nickname}
                        query={searchUser}
                      />
                    </span>
                  </div>
                </TableCell>
                <TableCell className="settings-table-cell font-mono text-xs text-content-secondary">
                  {formatDate(record.update_date)}
                </TableCell>
                <TableCell className="settings-table-cell text-content-secondary">
                  <span className="block truncate">
                    <SearchHighlight text={record.email} query={searchUser} />
                  </span>
                </TableCell>
                <TableCell className="settings-table-cell">
                  {readOnly || record.is_owner ? (
                    <span className="text-sm text-content-secondary">
                      {record.department_name ?? '-'}
                    </span>
                  ) : (
                    <div className="w-36">
                      <DepartmentSelect
                        value={record.department_id}
                        testId={`member-department-${record.user_id}`}
                        onChange={(departmentId) =>
                          updateTenantUserProfile({
                            userId: record.user_id,
                            departmentId,
                          })
                        }
                      />
                    </div>
                  )}
                </TableCell>
                <TableCell className="settings-table-cell text-content-secondary">
                  <span className="block truncate">{record.title ?? '-'}</span>
                </TableCell>
                <TableCell className="settings-table-cell">
                  {/*
                    The role picker belongs to rows the server will actually
                    reassign: never the caller's own row (`PUT .../role` refuses
                    `user_id == current_user.id`), never the owner's, never a
                    role the picker has no entry for - an `invite` row would
                    otherwise render a blank, unselectable control.
                  */}
                  {readOnly ||
                  record.is_owner ||
                  record.user_id === userInfo?.id ||
                  !isAssignableTenantRole(record.role) ? (
                    <RoleTag role={record.role} />
                  ) : (
                    <Select
                      value={record.role}
                      onValueChange={(role) =>
                        updateTenantUserRole({ userId: record.user_id, role })
                      }
                    >
                      {/* Same 32px control as the tag beside it, so the column
                          reads as one line whether or not the row is editable. */}
                      <SelectTrigger
                        className="ceramic-field h-8 w-28"
                        data-testid={`member-role-${record.user_id}`}
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={TenantRole.Admin}>
                          {t('setting.roleAdmin')}
                        </SelectItem>
                        <SelectItem value={TenantRole.Normal}>
                          {t('setting.roleMember')}
                        </SelectItem>
                      </SelectContent>
                    </Select>
                  )}
                </TableCell>
                <TableCell className="settings-table-cell">
                  <div className="flex justify-end">
                    {readOnly ||
                    record.is_owner ||
                    record.user_id === userInfo?.id ? null : (
                      <ConfirmDeleteDialog
                        title={t('deleteModal.delMember')}
                        onOk={async () => {
                          await deleteTenantUser({
                            userId: record.user_id,
                          });
                          return;
                        }}
                        content={{
                          node: (
                            <ConfirmDeleteDialogNode
                              avatar={{
                                avatar: record.avatar,
                                name: record.nickname,
                                isPerson: true,
                              }}
                              name={record.email}
                            ></ConfirmDeleteDialogNode>
                          ),
                        }}
                      >
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-8 p-0 text-content-tertiary hover:bg-state-error-5 hover:text-state-error"
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      </ConfirmDeleteDialog>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))
          ) : (
            <EmptyTableRow colSpan={7} label={t('common.noData')} />
          )}
        </TableBody>
      </Table>
    </div>
  );
};

export default UserTable;
