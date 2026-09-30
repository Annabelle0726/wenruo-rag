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

import { RAGFlowFormItem } from '@/components/ragflow-form';
import { MultiSelect } from '@/components/ui/multi-select';
import {
  useListDepartments,
  useListTenantUser,
} from '@/hooks/use-user-setting-request';
import { memo, useMemo } from 'react';
import { useTranslation } from 'react-i18next';

/**
 * The subjects of a `custom` dataset grant: the workspace's departments and the
 * individuals inside it.
 *
 * Both lists come from the workspace the dataset belongs to, because that is what
 * the server accepts: a department from another workspace, or a person who is not
 * a member, is refused rather than stored. The caller is a creator or a manager
 * (the settings page is manager-only), so the workspace roster is theirs to read.
 *
 * Individuals are labelled with their department — `张三（财务部）` — so two people
 * with the same name can be told apart.
 */
export const DatasetAuthorizationFields = memo(() => {
  const { t } = useTranslation();
  const { data: departments } = useListDepartments();
  const { data: members } = useListTenantUser();

  const departmentOptions = useMemo(
    () =>
      departments.map((department) => ({
        label: department.name,
        value: department.id,
      })),
    [departments],
  );

  const memberOptions = useMemo(
    () =>
      members.map((member) => ({
        label: member.department_name
          ? `${member.nickname}（${member.department_name}）`
          : member.nickname,
        value: member.user_id,
      })),
    [members],
  );

  return (
    <>
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <RAGFlowFormItem
          name="department_ids"
          label={t('knowledgeConfiguration.customDepartments')}
        >
          {(field) => (
            <div className="w-full space-y-1">
              <MultiSelect
                options={departmentOptions}
                value={field.value ?? []}
                onValueChange={field.onChange}
                placeholder={t(
                  'knowledgeConfiguration.customDepartmentsPlaceholder',
                )}
                popoverTestId="ds-authorization-department-popover"
                optionTestIdPrefix="ds-authorization-department"
                className="w-full"
              />
              {departmentOptions.length === 0 && (
                <p className="text-xs text-text-secondary">
                  {t('knowledgeConfiguration.customDepartmentsEmpty')}
                </p>
              )}
            </div>
          )}
        </RAGFlowFormItem>

        <RAGFlowFormItem
          name="user_ids"
          label={t('knowledgeConfiguration.customUsers')}
        >
          {(field) => (
            <div className="w-full space-y-1">
              <MultiSelect
                options={memberOptions}
                value={field.value ?? []}
                onValueChange={field.onChange}
                placeholder={t('knowledgeConfiguration.customUsersPlaceholder')}
                popoverTestId="ds-authorization-user-popover"
                optionTestIdPrefix="ds-authorization-user"
                className="w-full"
              />
              {memberOptions.length === 0 && (
                <p className="text-xs text-text-secondary">
                  {t('knowledgeConfiguration.customUsersEmpty')}
                </p>
              )}
            </div>
          )}
        </RAGFlowFormItem>
      </div>

      <div className="rounded-md border border-border-button/70 bg-background/60 px-3 py-2 text-xs leading-5 text-text-secondary">
        {t('knowledgeConfiguration.customHint')}
      </div>
    </>
  );
});

DatasetAuthorizationFields.displayName = 'DatasetAuthorizationFields';
