import { useHandleFilterSubmit } from '@/components/list-filter-bar/use-handle-filter-submit';
import { KnowledgeApiAction } from '@/hooks/use-knowledge-request';
import { useFetchUserInfo } from '@/hooks/use-user-setting-request';
import { IDataset } from '@/interfaces/database/dataset';
import { listDataset } from '@/services/knowledge-service';
import { getActiveTenantId } from '@/utils/active-tenant';
import { useQuery } from '@tanstack/react-query';

const DatasetListKeys = {
  accessible: (userId: string, tenantId: string | null, owners: string[]) =>
    [
      KnowledgeApiAction.FetchKnowledgeListByPage,
      'personal-list',
      userId,
      tenantId,
      owners,
    ] as const,
};

// Read only the SQL-filtered listing. Local preferences never supply additional
// IDs or change retrieval parameters. Assemble pages before personal sorting.
export async function fetchAccessibleDatasets(
  tenantId: string | null,
  owners: string[],
  signal: AbortSignal,
): Promise<IDataset[]> {
  const datasets = new Map<string, IDataset>();
  const pageSize = 100;
  for (let page = 1; ; page += 1) {
    if (signal.aborted || getActiveTenantId() !== tenantId) return [];
    const { data } = await listDataset({
      page,
      page_size: pageSize,
      owner_ids: owners,
    });
    if (signal.aborted || getActiveTenantId() !== tenantId || data.code !== 0)
      return [];
    const rows: IDataset[] = data.data ?? [];
    rows.forEach((row) => datasets.set(row.id, row));
    if (!rows.length || page * pageSize >= data.total || rows.length < pageSize)
      break;
  }
  return [...datasets.values()];
}

export function useDatasetList() {
  const { data: user } = useFetchUserInfo();
  const tenantId = getActiveTenantId();
  const filters = useHandleFilterSubmit();
  const owners = (filters.filterValue.owner ?? []) as string[];
  const query = useQuery({
    queryKey: DatasetListKeys.accessible(user.id, tenantId, owners),
    enabled: Boolean(user.id),
    gcTime: 0,
    queryFn: ({ signal }) => fetchAccessibleDatasets(tenantId, owners, signal),
  });
  return {
    ...filters,
    kbs: query.isError || !user.id ? [] : (query.data ?? []),
    loading: query.isFetching,
  };
}
