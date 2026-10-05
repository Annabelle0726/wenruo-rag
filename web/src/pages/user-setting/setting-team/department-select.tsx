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

/** Sentinel for "no department": a Select value cannot be null. */
export const NO_DEPARTMENT = '__none__';

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useListDepartments } from '@/hooks/use-user-setting-request';
import { useTranslation } from 'react-i18next';

interface DepartmentSelectProps {
  value: string | null | undefined;
  /** Receives `null` for the "no department" choice. */
  onChange: (departmentId: string | null) => void;
  testId?: string;
}

/**
 * Department picker with the empty workspace handled explicitly.
 *
 * With no departments yet there is nothing to choose, so the control is
 * disabled rather than offering a menu whose only entry is "no department" -
 * and it says why, because a greyed-out field with no explanation reads as a
 * permission problem. The tooltip sits on a wrapper: a disabled control emits
 * no pointer events of its own.
 */
export const DepartmentSelect = ({
  value,
  onChange,
  testId,
}: DepartmentSelectProps) => {
  const { t } = useTranslation();
  const { data: departments } = useListDepartments();
  const isEmpty = departments.length === 0;

  const select = (
    <Select
      value={value ?? NO_DEPARTMENT}
      disabled={isEmpty}
      onValueChange={(next) => onChange(next === NO_DEPARTMENT ? null : next)}
    >
      <SelectTrigger
        className="ceramic-field h-11"
        data-testid={testId}
        aria-label={t('setting.department')}
      >
        <SelectValue placeholder={t('setting.noDepartment')} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NO_DEPARTMENT}>
          {t('setting.noDepartment')}
        </SelectItem>
        {departments.map((department) => (
          <SelectItem key={department.id} value={department.id}>
            {department.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );

  if (!isEmpty) {
    return select;
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-block w-full cursor-not-allowed">{select}</span>
      </TooltipTrigger>
      <TooltipContent>{t('setting.departmentEmptyHint')}</TooltipContent>
    </Tooltip>
  );
};

export default DepartmentSelect;
