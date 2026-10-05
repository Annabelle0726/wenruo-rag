import {
  BulkOperateBar,
  BulkOperateItemType,
} from '@/components/bulk-operate-bar';
import { FileUploadDialog } from '@/components/file-upload-dialog';
import ListFilterBar from '@/components/list-filter-bar';
import { RenameDialog } from '@/components/rename-dialog';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useGoToPreviousPageOnEmpty } from '@/hooks/logic-hooks';
import { useClearSelectionOnPageChange } from '@/hooks/logic-hooks/use-clear-selection-on-page-change';
import {
  useRowSelection,
  useSelectedIds,
} from '@/hooks/logic-hooks/use-row-selection';
import { documentListIsSettled } from '@/hooks/document-list-state';
import { useFetchDocumentList } from '@/hooks/use-document-request';
import { TABLE_ROW_PITCH_PX } from '@/utils/list-capacity';
import { LucidePlus } from 'lucide-react';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { MetadataType } from '../components/metedata/constant';
import { useManageMetadata } from '../components/metedata/hooks/use-manage-modal';
import { ManageMetadataModal } from '../components/metedata/manage-modal';
import { useKnowledgeBaseContext } from '../contexts/knowledge-base-context';
import { DatasetTable } from './dataset-table';
import { ReparseDialog } from './reparse-dialog';
import { useBulkOperateDataset } from './use-bulk-operate-dataset';
import { useCreateEmptyDocument } from './use-create-empty-document';
import { useSelectDatasetFilters } from './use-select-filters';
import { useHandleUploadDocument } from './use-upload-document';

export default function Dataset() {
  const { t } = useTranslation();
  const {
    documentUploadVisible,
    hideDocumentUploadModal,
    showDocumentUploadModal,
    onDocumentUploadOk,
    documentUploadLoading,
  } = useHandleUploadDocument();
  const { knowledgeBase } = useKnowledgeBaseContext();
  const {
    searchString,
    documents,
    pagination,
    handleInputChange,
    setPagination,
    filterValue,
    handleFilterSubmit,
    loading,
    checkValue,
    state,
    retry,
  } = useFetchDocumentList();

  // Only a settled, successful read may move the page back. An empty *error* is
  // not an empty page - treating it as one turned a refused read into a jump to
  // the first page whose result was, of course, also never fetched.
  useGoToPreviousPageOnEmpty(
    documentListIsSettled(state) ? documents.length : undefined,
    loading,
  );

  const { filters, onOpenChange, filterGroup } = useSelectDatasetFilters();

  const {
    createLoading,
    onCreateOk,
    createVisible,
    hideCreateModal,
    showCreateModal,
  } = useCreateEmptyDocument();

  const {
    manageMetadataVisible,
    showManageMetadataModal,
    hideManageMetadataModal,
    tableData,
    config: metadataConfig,
  } = useManageMetadata();

  useEffect(() => {
    checkValue(filters);
  }, [filters]);

  const {
    rowSelection,
    rowSelectionIsEmpty,
    setRowSelection,
    selectedCount,
    clearRowSelection,
  } = useRowSelection();

  useClearSelectionOnPageChange(pagination, clearRowSelection);

  const {
    chunkNum,
    list,
    visible: reparseDialogVisible,
    hideModal: hideReparseDialogModal,
    handleRunClick: handleOperationIconClick,
  } = useBulkOperateDataset({
    documents,
    rowSelection,
    setRowSelection,
  });

  const { selectedIds: selectedRowKeys } = useSelectedIds(
    rowSelection,
    documents,
  );

  const handleAddMetadataWithDocuments = () => {
    showManageMetadataModal({
      type: MetadataType.Manage,
      isCanAdd: true,
      isEditField: false,
      isDeleteSingleValue: true,
      isAddValue: true,
      secondTitle: (
        <>
          {t('knowledgeDetails.metadata.selectFiles', {
            count: selectedCount,
          })}
        </>
      ),
      title: (
        <div className="flex flex-col gap-2">
          <div className="text-base font-normal">
            {t('knowledgeDetails.metadata.manageMetadata')}
          </div>
        </div>
      ),
      documentIds: selectedRowKeys,
    });
  };

  const updatedList = list.map((item) => {
    if (item.id === 'batch-metadata') {
      return {
        ...item,
        onClick: handleAddMetadataWithDocuments,
      };
    }
    return item;
  });

  return (
    <Card
      as="article"
      className="flex h-full min-h-0 flex-col border-0 bg-transparent shadow-none"
    >
      <CardHeader as="header" className="shrink-0 pb-4 space-y-0 pl-6 pr-0 pt-0">
        <ListFilterBar
          searchVariant="capsule"
          onSearchChange={handleInputChange}
          searchString={searchString}
          value={filterValue}
          filterGroup={filterGroup}
          onChange={handleFilterSubmit}
          onOpenChange={onOpenChange}
          filters={filters}
          className="items-end"
          leftPanel={
            <div>
              {/* The page-level title and subtitle carry the SAME type as the
                  retrieval testing header (`pages/dataset/testing/index.tsx`), which
                  is this area's reference: 24px/600/-0.025em in the primary ink over
                  14px/400 in the secondary ink (`text-2xl` and `text-sm` bring their
                  own line-heights). Only the type is shared - the two stay stacked
                  the way this toolbar has always laid them out, because that is
                  layout, not typography.

                  `font-normal` is the one class the reference does not need and
                  this one does: `list-filter-bar` wraps the whole panel in its own
                  `h1` (`text-base font-semibold`), so the subtitle would inherit
                  600 from it and read as bold next to the same subtitle elsewhere.
                  The title already states the weight it wants, hence only the
                  subtitle pins it. */}
              <h1 className="text-2xl font-semibold tracking-tight text-text-primary">
                {t('knowledgeDetails.subbarFiles')}
              </h1>
              <p className="text-sm font-normal text-text-secondary">
                {t('knowledgeDetails.datasetDescription')}
              </p>
            </div>
          }
        >
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button className="ceramic-cta h-8 rounded-[2px] px-3 text-xs font-medium gap-1.5">
                <LucidePlus className="size-3.5" />
                {t('knowledgeDetails.addFile')}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent className="w-auto min-w-40" align="end">
              <DropdownMenuItem onClick={showDocumentUploadModal}>
                {t('fileManager.uploadFile')}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={showCreateModal}>
                {t('knowledgeDetails.emptyFiles')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </ListFilterBar>

        {rowSelectionIsEmpty || (
          <BulkOperateBar
            className="!mt-2.5 !-mb-2.5"
            list={updatedList as BulkOperateItemType[]}
            count={selectedCount}
          />
        )}
      </CardHeader>

      <CardContent className="flex min-h-0 flex-1 flex-col p-0">
        {/* The region this page's table pages by.
            
            It is THIS box, not the whole dataset scroller: the scroller also
            carries the card header above the table (and the bulk bar that appears
            when a row is selected), so measuring it made the "space above the
            table" term move with the selection - a page size that changed when a
            checkbox was ticked. Here the box holds exactly the table and the pager,
            its height is whatever the flex column has left, and the pager is
            marked `data-list-footer` so it is subtracted.

            `data-list-item-height` is `DatasetTable`'s own row pitch (its
            `h-[38px]` rows plus the separator each draws), declared rather than
            measured so the first request already asks for a whole page instead of
            fetching a default and correcting itself. */}
        <div
          className="flex min-h-0 flex-1 flex-col overflow-auto"
          data-list-region=""
          data-list-item-height={TABLE_ROW_PITCH_PX}
        >
          <DatasetTable
            documents={documents}
            pagination={pagination}
            setPagination={setPagination}
            state={state}
            retry={retry}
            rowSelection={rowSelection}
            setRowSelection={setRowSelection}
            showManageMetadataModal={showManageMetadataModal}
            bulkOperateBarVisible={!rowSelectionIsEmpty}
          />
        </div>

        {documentUploadVisible && (
          <FileUploadDialog
            hideModal={hideDocumentUploadModal}
            onOk={onDocumentUploadOk}
            loading={documentUploadLoading}
            showParseOnCreation
            isTableParser={knowledgeBase?.chunk_method === 'table'}
          ></FileUploadDialog>
        )}
        {createVisible && (
          <RenameDialog
            hideModal={hideCreateModal}
            onOk={onCreateOk}
            loading={createLoading}
            title={t('knowledgeDetails.fileName')}
          ></RenameDialog>
        )}
        {manageMetadataVisible && (
          <ManageMetadataModal
            title={
              metadataConfig.title || (
                <div className="flex flex-col gap-2">
                  <div className="text-base font-normal">
                    {t('knowledgeDetails.metadata.manageMetadata')}
                  </div>
                  {/* <div className="text-sm text-text-secondary">
                    {t('knowledgeDetails.metadata.manageMetadataForDataset')}
                  </div> */}
                </div>
              )
            }
            visible={manageMetadataVisible}
            hideModal={() => {
              setRowSelection({});
              hideManageMetadataModal();
            }}
            // selectedRowKeys={selectedRowKeys}
            tableData={tableData}
            isCanAdd={metadataConfig.isCanAdd}
            isAddValue={metadataConfig.isAddValue}
            isVerticalShowValue={metadataConfig.isVerticalShowValue}
            isEditField={metadataConfig.isEditField}
            isDeleteSingleValue={metadataConfig.isDeleteSingleValue}
            secondTitle={metadataConfig.secondTitle}
            type={metadataConfig.type}
            documentIds={metadataConfig.documentIds}
            otherData={metadataConfig.record}
          />
        )}
        {reparseDialogVisible && (
          <ReparseDialog
            enable_metadata={knowledgeBase?.parser_config?.enable_metadata}
            handleOperationIconClick={handleOperationIconClick}
            chunk_num={chunkNum}
            visible={reparseDialogVisible}
            hideModal={hideReparseDialogModal}
          ></ReparseDialog>
        )}
      </CardContent>
    </Card>
  );
}
