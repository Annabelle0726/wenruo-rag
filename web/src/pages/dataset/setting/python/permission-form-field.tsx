import { DatasetAuthorizationFields } from '@/components/dataset-authorization-fields';
import { SelectWithSearch } from '@/components/originui/select-with-search';
import { RAGFlowFormItem } from '@/components/ragflow-form';
import { PermissionRole } from '@/constants/permission';
import { useMemo } from 'react';
import { useFormContext, useWatch } from 'react-hook-form';
import { useTranslation } from 'react-i18next';

export function PermissionFormField() {
  const { t } = useTranslation();
  const { control } = useFormContext();
  const permission = useWatch({ control, name: 'permission' });
  const teamOptions = useMemo(() => {
    return Object.values(PermissionRole).map((x) => ({
      label: t('knowledgeConfiguration.' + x),
      value: x,
    }));
  }, [t]);

  return (
    <section
      className="w-full max-w-[1120px] space-y-5 rounded-xl border border-table-border bg-table-row-alternate p-5"
      aria-label={t('listVisibility.settings')}
    >
      <RAGFlowFormItem
        name="permission"
        label={t('knowledgeConfiguration.permissions')}
        // The mode is also what a `custom` grant hangs off, so the tooltip has to
        // name all three rather than only the team case.
        tooltip={t('knowledgeConfiguration.permissionsTip')}
        labelClassName="font-medium"
        valueClassName="max-w-[520px]"
        className="items-start gap-6"
        horizontal
      >
        <SelectWithSearch
          options={teamOptions}
          triggerClassName="w-full"
          testId="ds-settings-basic-permissions-select"
        ></SelectWithSearch>
      </RAGFlowFormItem>

      {permission === PermissionRole.Custom && <DatasetAuthorizationFields />}
    </section>
  );
}
