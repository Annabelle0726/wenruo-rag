import { EmptyCardType } from '@/components/empty/constant';
import { EmptyAppCard } from '@/components/empty/empty';
import { FilterButton } from '@/components/list-filter-bar';
import { FilterPopover } from '@/components/list-filter-bar/filter-popover';
import { RenameDialog } from '@/components/rename-dialog';
import { Button } from '@/components/ui/button';
import { RAGFlowPagination } from '@/components/ui/ragflow-pagination';
import { useDatasetPreferences } from '@/hooks/use-dataset-preferences';
import { useGetPaginationWithRouter } from '@/hooks/logic-hooks';
import { useDatasetList } from './use-dataset-list';
import { UserSettingKeys } from '@/hooks/use-user-setting-request';
import { TABLE_ROW_PITCH_PX } from '@/utils/list-capacity';
import { useQueryClient } from '@tanstack/react-query';
import { pick } from 'lodash';
import { Eye, EyeOff, Plus } from 'lucide-react';
import { useCallback, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router';
import { arrangeDatasets } from './arrange-datasets';
import { DatasetTable } from './dataset-table';
import { DatasetCreatingDialog } from './dataset-creating-dialog';
import { useSaveKnowledge } from './hooks';
import { DatasetQueryPanel } from './query-panel';
import { useDatasetQuery } from './use-dataset-query';
import { useRenameDataset } from './use-rename-dataset';
import { useSelectOwners } from './use-select-owners';

export default function Datasets() {
  const { t } = useTranslation();
  const {
    visible,
    hideModal,
    showModal,
    onCreateOk,
    loading: creatingLoading,
  } = useSaveKnowledge();

  const { kbs, filterValue, handleFilterSubmit, loading } = useDatasetList();
  const { pagination, setPagination } = useGetPaginationWithRouter();

  const owners = useSelectOwners();

  const {
    datasetRenameLoading,
    initialDatasetName,
    onDatasetRenameOk,
    datasetRenameVisible,
    hideDatasetRenameModal,
    showDatasetRenameModal,
  } = useRenameDataset();

  const {
    query,
    setCategory,
    setKeyword,
    setCreatedFrom,
    setCreatedTo,
    reset,
    filter,
  } = useDatasetQuery();

  const { pinnedIds, hiddenIds, showHidden, setShowHidden } =
    useDatasetPreferences();

  const filteredDatasets = useMemo(() => filter(kbs ?? []), [filter, kbs]);

  // Pinned datasets come first and hidden ones are dropped, both as this user's
  // own view of datasets the server already narrowed to what they may read.
  const datasets = useMemo(
    () =>
      arrangeDatasets({
        datasets: filteredDatasets,
        pinnedIds,
        hiddenIds,
        showHidden,
      }),
    [filteredDatasets, pinnedIds, hiddenIds, showHidden],
  );

  const hiddenCount = kbs.filter((dataset) =>
    hiddenIds.includes(dataset.id),
  ).length;
  const pageSize = pagination.pageSize ?? 10;
  const current = Math.min(
    pagination.current ?? 1,
    Math.max(1, Math.ceil(datasets.length / pageSize)),
  );
  const pageDatasets = datasets.slice(
    (current - 1) * pageSize,
    current * pageSize,
  );

  const handleToggleShowHidden = useCallback(() => {
    setShowHidden(!showHidden);
  }, [setShowHidden, showHidden]);

  const handlePageChange = useCallback(
    (page: number, pageSize?: number) => {
      setPagination({ page, pageSize });
    },
    [setPagination],
  );
  const [searchUrl, setSearchUrl] = useSearchParams();
  const isCreate = searchUrl.get('isCreate') === 'true';
  const queryClient = useQueryClient();
  useEffect(() => {
    if (isCreate) {
      queryClient.invalidateQueries({ queryKey: UserSettingKeys.tenantInfo() });
      showModal();
      searchUrl.delete('isCreate');
      setSearchUrl(searchUrl);
    }
  }, [isCreate, showModal, searchUrl, setSearchUrl, queryClient]);

  /** Owner stays a popover filter: it is a tenant-scoped multi-select, not one of
   *  the panel's three single-value conditions. */
  const ownerFilterCount = useMemo(
    () => (Array.isArray(filterValue?.owner) ? filterValue.owner.length : 0),
    [filterValue],
  );

  return (
    <article
      className="flex size-full min-w-0 flex-col overflow-auto"
      data-testid="datasets-list"
    >
      <header className="page-gutter flex min-w-0 items-center justify-between gap-4 py-3">
        <h1 className="truncate text-base font-semibold text-text-primary">
          {t('header.dataset')}
        </h1>
        <div className="flex shrink-0 items-center gap-2">
          {hiddenCount > 0 && (
            <Button
              variant="ghost"
              className="h-8 shrink-0 gap-1.5 px-3 text-xs font-medium text-text-secondary"
              onClick={handleToggleShowHidden}
              data-testid="dataset-show-hidden"
            >
              {showHidden ? (
                <EyeOff className="size-3.5" />
              ) : (
                <Eye className="size-3.5" />
              )}
              {t('common.showHidden', { count: hiddenCount })}
            </Button>
          )}

          <FilterPopover
            value={filterValue}
            onChange={handleFilterSubmit}
            filters={owners}
          >
            <FilterButton count={ownerFilterCount} />
          </FilterPopover>

          <Button
            className="ceramic-cta h-8 shrink-0 rounded-[2px] px-3 text-xs font-medium gap-1.5"
            onClick={showModal}
          >
            <Plus className="size-3.5" />
            {t('knowledgeList.createKnowledgeBase')}
          </Button>
        </div>
      </header>

      <DatasetQueryPanel
        className="page-gutter mb-3 border-x-0 border-t-0"
        query={query}
        onCategoryChange={setCategory}
        onKeywordChange={setKeyword}
        onCreatedFromChange={setCreatedFrom}
        onCreatedToChange={setCreatedTo}
        onReset={reset}
      />

      {/* The list region exists before the rows do: the page size is how many
          complete rows this region holds, so it has to be measurable from the
          first render (and the table shows its own skeleton inside it). The
          declared height is `DatasetTable`'s own row pitch, so the first request
          already asks for a whole page rather than a default that is corrected
          afterwards. */}
      {loading || kbs.length || query.keyword ? (
        <>
          <div
            className="page-gutter min-h-0 flex-1 overflow-auto"
            data-list-region=""
            data-list-item-height={TABLE_ROW_PITCH_PX}
          >
            <DatasetTable
              datasets={pageDatasets}
              loading={loading}
              hiddenDatasetIds={showHidden ? hiddenIds : []}
              showDatasetRenameModal={showDatasetRenameModal}
            />
          </div>

          <footer className="page-gutter py-3">
            <RAGFlowPagination
              {...pick(pagination, 'pageSize')}
              current={current}
              total={datasets.length}
              onChange={handlePageChange}
            />
          </footer>
        </>
      ) : (
        <div className="page-gutter pb-6">
          <EmptyAppCard
            showIcon
            type={EmptyCardType.Dataset}
            onClick={() => showModal()}
          />
        </div>
      )}

      {visible && (
        <DatasetCreatingDialog
          hideModal={hideModal}
          onOk={onCreateOk}
          loading={creatingLoading}
        ></DatasetCreatingDialog>
      )}
      {datasetRenameVisible && (
        <RenameDialog
          hideModal={hideDatasetRenameModal}
          onOk={onDatasetRenameOk}
          initialName={initialDatasetName}
          loading={datasetRenameLoading}
        ></RenameDialog>
      )}
    </article>
  );
}
