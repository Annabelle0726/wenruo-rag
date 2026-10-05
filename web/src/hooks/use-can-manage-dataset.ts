import { IDataset } from '@/interfaces/database/dataset';
import { canManageTenant } from '@/utils/tenant-role';
import {
  useFetchTenantInfo,
  useFetchUserInfo,
} from './use-user-setting-request';

// UI affordance only; the server remains authoritative for every mutation.
export function useCanManageDataset(
  dataset: Pick<IDataset, 'created_by' | 'tenant_id'> | null,
) {
  const { data: user } = useFetchUserInfo();
  const { data: tenant } = useFetchTenantInfo();
  return Boolean(
    user.id &&
    dataset &&
    (dataset.created_by === user.id ||
      (dataset.tenant_id === tenant.tenant_id && canManageTenant(tenant.role))),
  );
}
