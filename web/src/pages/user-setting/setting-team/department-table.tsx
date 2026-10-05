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

import { ConfirmDeleteDialog } from '@/components/confirm-delete-dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  useDepartmentMutations,
  useListDepartments,
} from '@/hooks/use-user-setting-request';
import { Check, Pencil, Plus, Trash2, X } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

/**
 * Flat department editor for one workspace.
 *
 * `parent_id` exists in the schema so a tree can be rendered later; the MVP
 * keeps departments flat, which is also why nothing here offers a parent
 * picker. Deleting is refused by the server while members are still placed in
 * the department, so the error it returns is the only feedback needed.
 */
const DepartmentTable = ({ readOnly }: { readOnly: boolean }) => {
  const { t } = useTranslation();
  const { data: departments } = useListDepartments();
  const { create, rename, remove } = useDepartmentMutations();
  const [newName, setNewName] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState('');

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    const result = await create(name);
    if (result?.code === 0) {
      setNewName('');
    }
  };

  const handleRename = async () => {
    const name = editingName.trim();
    if (!name || !editingId) {
      setEditingId(null);
      return;
    }
    const result = await rename({ departmentId: editingId, name });
    if (result?.code === 0) {
      setEditingId(null);
    }
  };

  return (
    // The same row geometry the roster tables use (44px rows, a hairline between
    // them, actions on the right), so a department list and a member list read as
    // two views of one settings module rather than two different products.
    <div className="flex flex-col">
      <ul className="divide-y divide-cable-hairline">
        {departments.map((department) => (
          <li
            key={department.id}
            className="flex h-11 items-center gap-2 px-3.5"
            data-testid={`department-row-${department.id}`}
          >
            {editingId === department.id ? (
              <>
                <Input
                  value={editingName}
                  onChange={(e) => setEditingName(e.target.value)}
                  className="ceramic-field h-8 flex-1"
                  autoFocus
                />
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8 text-content-tertiary hover:text-text-primary"
                  aria-label={t('common.ok')}
                  onClick={handleRename}
                >
                  <Check className="size-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8 text-content-tertiary hover:text-text-primary"
                  aria-label={t('common.cancel')}
                  onClick={() => setEditingId(null)}
                >
                  <X className="size-4" />
                </Button>
              </>
            ) : (
              <>
                <span className="flex-1 truncate text-sm text-text-primary">
                  {department.name}
                </span>
                {!readOnly && (
                  <>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-8 text-content-tertiary hover:text-text-primary"
                      aria-label={t('setting.renameDepartment')}
                      onClick={() => {
                        setEditingId(department.id);
                        setEditingName(department.name);
                      }}
                    >
                      <Pencil className="size-4" />
                    </Button>
                    <ConfirmDeleteDialog onOk={() => remove(department.id)}>
                      <Button
                        variant="delete"
                        size="icon"
                        className="size-8"
                        aria-label={t('setting.deleteDepartment')}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </ConfirmDeleteDialog>
                  </>
                )}
              </>
            )}
          </li>
        ))}
      </ul>

      {readOnly ? null : (
        <div className="flex items-center gap-2 border-t border-cable-hairline bg-cable-surface-muted px-3.5 py-2">
          <Input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={t('setting.departmentNamePlaceholder')}
            className="ceramic-field h-8 flex-1"
            data-testid="new-department-name"
          />
          <Button
            variant="outline"
            size="sm"
            className="h-8 shrink-0"
            data-testid="add-department"
            onClick={handleCreate}
          >
            <Plus className="size-4" />
            {t('setting.addDepartment')}
          </Button>
        </div>
      )}
    </div>
  );
};

export default DepartmentTable;
