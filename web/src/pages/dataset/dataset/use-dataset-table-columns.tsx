import { useCanManageDataset } from '@/hooks/use-can-manage-dataset';
import { useKnowledgeBaseContext } from '../contexts/knowledge-base-context';
import { FileIcon } from '@/components/icon-font';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Switch } from '@/components/ui/switch';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useNavigatePage } from '@/hooks/logic-hooks/navigate-hooks';
import { UseRowSelectionType } from '@/hooks/logic-hooks/use-row-selection';
import { useSetDocumentStatus } from '@/hooks/use-document-request';
import { IDocumentInfo } from '@/interfaces/database/document';
import { cn } from '@/lib/utils';
import { formatDate } from '@/utils/date';
import { ColumnDef } from '@tanstack/table-core';
import { ArrowUpDown } from 'lucide-react';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router';
import { MetadataType } from '../components/metedata/constant';
import { ShowManageMetadataModalProps } from '../components/metedata/interface';
import { useDocumentVisibility } from './use-document-visibility';
import { DatasetActionCell } from './dataset-action-cell';
import { ParseDropdownButton, ParsingStatusCell } from './parsing-status-cell';
import { UseChangeDocumentParserShowType } from './use-change-document-parser';
import { UseRenameDocumentShowType } from './use-rename-document';

type UseDatasetTableColumnsType = UseChangeDocumentParserShowType &
  UseRenameDocumentShowType &
  Pick<UseRowSelectionType, 'setRowSelection'> & {
    showLog: (record: IDocumentInfo) => void;
    showManageMetadataModal: (config: ShowManageMetadataModalProps) => void;
  };

/**
 * Column geometry, declared once.
 *
 * Every column except the name has a fixed width, so the name takes whatever the
 * region has left and truncates while the others never change size. That is what
 * stops a narrower region from squeezing the other columns into wrapped text: a
 * wrapped cell is two lines tall, and the table pages by row height, so before
 * this a collapsed sidebar turned seven rows into five.
 *
 * The row height itself is the contract `dataset/index.tsx` declares
 * (`data-list-item-height`), and these widths are what make it hold.
 */
const DocumentColumnWidth = {
  select: 'w-[3.5rem]',
  name: 'min-w-0 overflow-hidden',
  createTime: 'w-[11rem]',
  status: 'w-[5rem]',
  chunkCount: 'w-[6rem]',
  metadata: 'w-[8.5rem]',
  parser: 'w-[11rem]',
  actions: 'w-[10rem]',
} as const;

export function useDatasetTableColumns({
  showChangeParserModal,
  showRenameModal,
  showManageMetadataModal,
  showLog,
  setRowSelection,
}: UseDatasetTableColumnsType) {
  const { t } = useTranslation('translation', {
    keyPrefix: 'knowledgeDetails',
  });
  // const { dataSourceInfo } = useDataSourceInfo();
  const { navigateToChunkParsedResult } = useNavigatePage();
  const { setDocumentStatus, loading: statusLoading } = useSetDocumentStatus();
  const { knowledgeBase } = useKnowledgeBaseContext();
  const canManage = useCanManageDataset(knowledgeBase);
  const { id: datasetId } = useParams();
  const { parentHidden } = useDocumentVisibility();

  const columns: ColumnDef<IDocumentInfo>[] = useMemo(
    () => [
      {
        id: 'select',
        header: ({ table }) => (
          <Checkbox
            checked={
              table.getIsAllPageRowsSelected() ||
              (table.getIsSomePageRowsSelected() && 'indeterminate')
            }
            onCheckedChange={(value) =>
              table.toggleAllPageRowsSelected(!!value)
            }
            aria-label="Select all"
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            checked={row.getIsSelected()}
            onCheckedChange={(value) => row.toggleSelected(!!value)}
            aria-label="Select row"
          />
        ),
        enableSorting: false,
        enableHiding: false,
        meta: { headerCellClassName: DocumentColumnWidth.select },
      },
      {
        accessorKey: 'name',
        header: ({ column }) => {
          return (
            <div className="flex items-center gap-1">
              {t('name')}

              <Button
                variant="ghost"
                size="icon-xs"
                onClick={() =>
                  column.toggleSorting(column.getIsSorted() === 'asc')
                }
              >
                <ArrowUpDown />
              </Button>
            </div>
          );
        },
        // The one column without a declared width: it takes the slack the fixed
        // columns leave. `min-w-0` plus the truncating span is what lets it give
        // space back, so a long file name ellipsizes instead of widening the table
        // and deforming every other column.
        meta: {
          cellClassName: DocumentColumnWidth.name,
        },
        cell: ({ row }) => {
          const name: string = row.getValue('name');

          return (
            <Tooltip>
              <TooltipTrigger asChild>
                <div
                  className="flex min-w-0 items-center gap-2 cursor-pointer"
                  onClick={navigateToChunkParsedResult(
                    row.original.id,
                    row.original.dataset_id,
                  )}
                >
                  <FileIcon name={name}></FileIcon>
                  <span
                    className={cn(
                      'min-w-0 truncate',
                      (parentHidden || row.original.status === '0') &&
                        'text-text-secondary',
                    )}
                  >
                    {name}
                  </span>
                  {(parentHidden || row.original.status === '0') && (
                    <span
                      className="shrink-0 border border-border-button px-1.5 py-0.5 text-xs text-text-secondary"
                      title={t(
                        parentHidden ? 'parentHiddenFile' : 'hiddenFile',
                      )}
                    >
                      {t(parentHidden ? 'parentHiddenFile' : 'hiddenFile')}
                    </span>
                  )}
                </div>
              </TooltipTrigger>
              <TooltipContent>
                <p>{name}</p>
              </TooltipContent>
            </Tooltip>
          );
        },
      },
      {
        accessorKey: 'create_time',
        header: ({ column }) => {
          return (
            <div className="flex items-center gap-1">
              {t('uploadDate')}

              <Button
                variant="ghost"
                size="icon-xs"
                onClick={() =>
                  column.toggleSorting(column.getIsSorted() === 'asc')
                }
              >
                <ArrowUpDown />
              </Button>
            </div>
          );
        },
        meta: { headerCellClassName: DocumentColumnWidth.createTime },
        cell: ({ row }) => (
          <time
            className="lowercase"
            dateTime={new Date(row.getValue('create_time')).toISOString()}
          >
            {formatDate(row.getValue('create_time'))}
          </time>
        ),
      },
      {
        accessorKey: 'status',
        header: t('enabled'),
        meta: { headerCellClassName: DocumentColumnWidth.status },
        cell: ({ row }) => {
          const id = row.original.id;
          return (
            <Switch
              checked={!parentHidden && row.getValue('status') === '1'}
              disabled={parentHidden || !canManage || statusLoading}
              aria-label={t('enabled')}
              onCheckedChange={(e) => {
                setDocumentStatus({
                  status: e,
                  documentId: id,
                  datasetId: datasetId!,
                });
              }}
            />
          );
        },
      },
      {
        accessorKey: 'chunk_count',
        header: t('chunkNumber'),
        meta: { headerCellClassName: DocumentColumnWidth.chunkCount },
        cell: ({ row }) => (
          <div className="capitalize">{row.getValue('chunk_count')}</div>
        ),
      },
      {
        accessorKey: 'meta_fields',
        header: t('metadata.metadata'),
        meta: { headerCellClassName: DocumentColumnWidth.metadata },
        cell: ({ row }) => {
          const length = Object.keys(row.getValue('meta_fields') || {}).length;
          return (
            <Button
              variant="static"
              size="auto"
              className="max-w-full min-w-0"
              onClick={() => {
                showManageMetadataModal({
                  isEditField: false,
                  isCanAdd: true,
                  isAddValue: true,
                  type: MetadataType.UpdateSingle,
                  record: row.original,
                  title: (
                    <div className="flex flex-col gap-2 w-full">
                      <div className="text-base font-normal">
                        {t('metadata.editMetadata')}
                      </div>
                    </div>
                  ),
                  secondTitle: (
                    <div className="w-full flex gap-1 text-sm text-text-secondary">
                      <FileIcon name={row.original.name}></FileIcon>
                      <div className="truncate">{row.original.name}</div>
                    </div>
                  ),
                  isDeleteSingleValue: true,
                  documentIds: [row.original.id],
                });
              }}
            >
              {length + ' fields'}
            </Button>
          );
        },
      },
      {
        accessorKey: 'run',
        header: t('Parse'),
        meta: { headerCellClassName: DocumentColumnWidth.parser },
        cell: ({ row }) => {
          // `pipeline_name` is free text with no length limit, so this cell is
          // the column's min-content floor: the column width caps it and the
          // wrapper truncates, which keeps a long ingestion-pipeline name from
          // widening the whole table. The dropdown already carries the full name
          // in its tooltip.
          return (
            <div className="max-w-full min-w-0 truncate">
              <ParseDropdownButton
                record={row.original}
                showChangeParserModal={showChangeParserModal}
              />
            </div>
          );
        },
      },
      {
        id: 'run-status',
        header: '',
        cell: ({ row }) => {
          return (
            <ParsingStatusCell
              record={row.original}
              showChangeParserModal={showChangeParserModal}
              showLog={showLog}
            />
          );
        },
      },
      {
        id: 'actions',
        header: t('action'),
        enableHiding: false,
        meta: { headerCellClassName: DocumentColumnWidth.actions },
        cell: ({ row }) => {
          const record = row.original;

          return (
            <DatasetActionCell
              record={record}
              showRenameModal={showRenameModal}
              setRowSelection={setRowSelection}
            />
          );
        },
      },
    ],
    [
      t,
      navigateToChunkParsedResult,
      setDocumentStatus,
      statusLoading,
      canManage,
      parentHidden,
      datasetId,
      showChangeParserModal,
      showRenameModal,
      showManageMetadataModal,
      showLog,
      setRowSelection,
    ],
  );

  return columns;
}
