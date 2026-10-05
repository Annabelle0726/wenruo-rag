import { SelectWithSearch } from '@/components/originui/select-with-search';
import { RAGFlowFormItem } from '@/components/ragflow-form';
import { PermissionRole } from '@/constants/permission';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

/**
 * The modes this variant can actually store.
 *
 * Fine-grained authorization (`custom`) is served by the Python backend's
 * `/datasets/<id>/authorization` endpoint. This variant has no such route, so
 * offering the option would promise a grant that is never written — it stays out
 * of the list rather than being sent and dropped.
 */
const GoPermissionRoles = [PermissionRole.Me, PermissionRole.Team];

export function PermissionFormField() {
  const { t } = useTranslation();
  const teamOptions = useMemo(() => {
    return GoPermissionRoles.map((x) => ({
      label: t('knowledgeConfiguration.' + x),
      value: x,
    }));
  }, [t]);

  return (
    <RAGFlowFormItem
      name="permission"
      label={t('knowledgeConfiguration.permissions')}
      tooltip={t('knowledgeConfiguration.permissionsTip')}
      horizontal
    >
      <SelectWithSearch
        options={teamOptions}
        triggerClassName="w-full"
        testId="ds-settings-basic-permissions-select"
      ></SelectWithSearch>
    </RAGFlowFormItem>
  );
}
