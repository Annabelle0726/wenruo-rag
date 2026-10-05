import { RenameDialog } from '@/components/rename-dialog';
import { Button } from '@/components/ui/button';
import { useNavigatePage } from '@/hooks/logic-hooks/navigate-hooks';
import { useDatasetPreferences } from '@/hooks/use-dataset-preferences';
import { useDatasetList } from '../datasets/use-dataset-list';
import { arrangeDatasets } from '../datasets/arrange-datasets';
import { Plus } from 'lucide-react';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { DatasetTable } from '../datasets/dataset-table';
import { DatasetQueryPanel } from '../datasets/query-panel';
import { useDatasetQuery } from '../datasets/use-dataset-query';
import { useRenameDataset } from '../datasets/use-rename-dataset';
import { SectionHeading } from './home-layout';

export function Datasets() {
  const { t } = useTranslation();
  const { kbs, loading } = useDatasetList();
  const {
    datasetRenameLoading,
    initialDatasetName,
    onDatasetRenameOk,
    datasetRenameVisible,
    hideDatasetRenameModal,
    showDatasetRenameModal,
  } = useRenameDataset();
  const { navigateToDatasetList } = useNavigatePage();

  const {
    query,
    setCategory,
    setKeyword,
    setCreatedFrom,
    setCreatedTo,
    reset,
    filter,
  } = useDatasetQuery();

  const { pinnedIds, hiddenIds } = useDatasetPreferences();
  const datasets = useMemo(
    () =>
      arrangeDatasets({
        datasets: filter(kbs),
        pinnedIds,
        hiddenIds,
        showHidden: false,
      }),
    [filter, kbs, pinnedIds, hiddenIds],
  );

  return (
    <section>
      <SectionHeading iconName="datasets" label={t('header.dataset')}>
        <Button
          className="ceramic-cta h-8 rounded-[2px] px-3 text-xs font-medium gap-1.5"
          onClick={() => navigateToDatasetList({ isCreate: true })}
        >
          <Plus className="size-3.5" />
          {t('knowledgeList.createKnowledgeBase')}
        </Button>
      </SectionHeading>

      <DatasetQueryPanel
        className="mb-3"
        query={query}
        onCategoryChange={setCategory}
        onKeywordChange={setKeyword}
        onCreatedFromChange={setCreatedFrom}
        onCreatedToChange={setCreatedTo}
        onReset={reset}
      />

      <DatasetTable
        datasets={datasets}
        loading={loading}
        showDatasetRenameModal={showDatasetRenameModal}
      />

      {datasetRenameVisible && (
        <RenameDialog
          hideModal={hideDatasetRenameModal}
          onOk={onDatasetRenameOk}
          initialName={initialDatasetName}
          loading={datasetRenameLoading}
        />
      )}
    </section>
  );
}
