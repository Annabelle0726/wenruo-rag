import { EmptyType } from '@/components/empty/constant';
import Empty from '@/components/empty/empty';
import FileStatusBadge from '@/components/file-status-badge';
import { FileIcon, IconFontFill } from '@/components/icon-font';
import { RAGFlowAvatar } from '@/components/ragflow-avatar';
import { Button } from '@/components/ui/button';
import { RAGFlowPagination } from '@/components/ui/ragflow-pagination';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { TableSkeleton } from '@/components/table-skeleton';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  ProcessingType,
  ProcessingTypeMap,
  RunningStatusMap,
} from '@/constants/knowledge';
import { useTranslate } from '@/hooks/common-hooks';
import { cn } from '@/lib/utils';
import { TABLE_ROW_PITCH_PX } from '@/utils/list-capacity';
import { useDataSourceInfo } from '@/components/data-source/constant';
import { IDataSourceInfoMap } from '@/components/data-source/interface';
import { formatDate, formatSecondsToHumanReadable } from '@/utils/date';
import {
  ColumnDef,
  ColumnFiltersState,
  Row,
  SortingState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { TFunction } from 'i18next';
import { ArrowUpDown, Eye, MonitorUp } from 'lucide-react';
import { FC, useMemo, useState } from 'react';
import { RunningStatus } from '../dataset/constant';
import ProcessLogModal, { ILogInfo } from '../process-log-modal';
import { LogTabs } from './dataset-common';
import { DocumentLog, FileLogsTableProps, IFileLogItem } from './interface';

/**
 * The log table's geometry, declared once for both tabs and taken from the
 * knowledge base file list (`pages/dataset/dataset/dataset-table.tsx`):
 *
 *   header  a 40px band in `--table-head-ink` at 13px/600 over `--table-header-bg`
 *   rows    a fixed 38px, `--table-border` hairlines, zebra from `--table-row-base`
 *           / `--table-row-alternate` (white and a very light green, both retuned
 *           for dark mode in `tailwind.css`), `--table-row-hover` on hover
 *
 * The row height has to be a CONSTANT, not a consequence of the content: the page
 * size is derived from it, so a cell that wrapped at a narrower width used to make
 * every row taller and the table page by fewer logs - a collapse/expand of the
 * dataset sidebar moved the page size from 8 to 6 and re-requested the list. Every
 * cell is `whitespace-nowrap`, the two free-text columns (the log id and the file
 * name) truncate, and the rest declare a width below.
 *
 * Every width is the widest thing that column renders plus its own padding, read
 * off the live page: the status badge is a fixed 75px pill, the start date is the
 * same `formatDate` string as the file list's, and the id column keeps room for
 * nine characters of hex before it ellipsizes into its tooltip. The sum (~800px)
 * leaves the file name a real share of a 1280px desktop with the sidebar open.
 */
const LogRowClass = cn(
  'group h-[38px] border-b border-table-border',
  'hover:bg-table-row-hover data-[state=selected]:bg-table-row-hover',
  'odd:bg-table-row-base even:bg-table-row-alternate',
);
const LogHeadCellClass = 'h-10 text-[13px] font-semibold text-table-head-ink';
const LogColumnWidth = {
  /** Not useful enough to be worth 250px of hex: truncated, with a tooltip. */
  id: 'w-[9rem]',
  /** The one flexible column: it takes what the fixed ones leave and truncates. */
  fileName: 'min-w-0 overflow-hidden',
  source: 'w-[4.5rem]',
  pipeline: 'w-[7rem]',
  startDate: 'w-[11rem]',
  task: 'w-[6rem]',
  status: 'w-[7.5rem]',
  operations: 'w-[5rem]',
} as const;

export const getFileLogsTableColumns = (
  t: TFunction<'translation', string>,
  showLog: (row: Row<IFileLogItem & DocumentLog>, active: LogTabs) => void,
  dataSourceInfo: IDataSourceInfoMap,
) => {
  // const { t } = useTranslate('knowledgeDetails');
  const columns: ColumnDef<IFileLogItem & DocumentLog>[] = [
    // {
    //   id: 'select',
    //   header: ({ table }) => (
    //     <input
    //       type="checkbox"
    //       checked={table.getIsAllRowsSelected()}
    //       onChange={table.getToggleAllRowsSelectedHandler()}
    //       className="rounded bg-gray-900 text-blue-500 focus:ring-blue-500"
    //     />
    //   ),
    //   cell: ({ row }) => (
    //     <input
    //       type="checkbox"
    //       checked={row.getIsSelected()}
    //       onChange={row.getToggleSelectedHandler()}
    //       className="rounded border-gray-600 bg-gray-900 text-blue-500 focus:ring-blue-500"
    //     />
    //   ),
    // },
    {
      accessorKey: 'id',
      header: 'ID',
      meta: { headerCellClassName: LogColumnWidth.id },
      cell: ({ row }) => (
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="min-w-0 truncate text-text-primary">
              {row.original.id}
            </div>
          </TooltipTrigger>
          <TooltipContent>
            <p>{row.original.id}</p>
          </TooltipContent>
        </Tooltip>
      ),
    },
    {
      accessorKey: 'fileName',
      header: t('fileName'),
      meta: { cellClassName: LogColumnWidth.fileName },
      cell: ({ row }) => (
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex min-w-0 gap-2 cursor-pointer">
              <FileIcon name={row.original.document_name}></FileIcon>
              <span className={cn('min-w-0 truncate')}>
                {row.original.document_name}
              </span>
            </div>
          </TooltipTrigger>
          <TooltipContent>
            <p>{row.original.document_name}</p>
          </TooltipContent>
        </Tooltip>
      ),
    },
    {
      accessorKey: 'source_from',
      header: t('source'),
      meta: { headerCellClassName: LogColumnWidth.source },
      cell: ({ row }) => (
        <div className="text-text-primary">
          {row.original.source_from === 'local' ||
          row.original.source_from === '' ? (
            <div className="bg-accent-primary-5 w-6 h-6 rounded-full flex items-center justify-center">
              <MonitorUp className="text-accent-primary" size={16} />
            </div>
          ) : dataSourceInfo[
              row.original.source_from as keyof typeof dataSourceInfo
            ] ? (
            <div className="w-6 h-6 flex items-center justify-center">
              {
                dataSourceInfo[
                  row.original.source_from as keyof typeof dataSourceInfo
                ].icon
              }
            </div>
          ) : (
            <div className="w-6 h-6 flex items-center justify-center">
              <MonitorUp className="text-accent-primary" size={16} />
            </div>
          )}
        </div>
      ),
    },
    {
      accessorKey: 'pipeline_title',
      header: t('dataPipelineTitle'),
      meta: { headerCellClassName: LogColumnWidth.pipeline },
      cell: ({ row }) => {
        const title = row.original.pipeline_title;
        const pipelineTitle = title === 'naive' ? 'general' : title;
        return (
          <div className="flex min-w-0 items-center gap-2 text-text-primary">
            <RAGFlowAvatar
              avatar={row.original.avatar}
              name={pipelineTitle}
              className="size-4 shrink-0"
            />
            <span className="truncate">{pipelineTitle}</span>
          </div>
        );
      },
    },
    {
      accessorKey: 'process_begin_at',
      header: ({ column }) => {
        return (
          <div className="flex items-center gap-1">
            {t('startDate')}

            <Button
              variant="ghost"
              size="icon-xs"
              onClick={() =>
                column.toggleSorting(column.getIsSorted() === 'asc')
              }
            >
              <ArrowUpDown className="size-[1em]" />
            </Button>
          </div>
        );
      },
      meta: { headerCellClassName: LogColumnWidth.startDate },
      cell: ({ row }) => (
        <div className="text-text-primary">
          {formatDate(row.original.process_begin_at)}
        </div>
      ),
    },
    {
      accessorKey: 'task_type',
      header: t('task'),
      meta: { headerCellClassName: LogColumnWidth.task },
      cell: ({ row }) => (
        <div className="text-text-primary">{row.original.task_type}</div>
      ),
    },
    {
      accessorKey: 'operation_status',
      header: t('status'),
      meta: { headerCellClassName: LogColumnWidth.status },
      cell: ({ row }) => (
        <FileStatusBadge
          status={row.original.operation_status as RunningStatus}
          name={
            RunningStatusMap[row.original.operation_status as RunningStatus]
          }
        />
      ),
    },
    {
      id: 'operations',
      header: t('operations'),
      meta: { headerCellClassName: LogColumnWidth.operations },
      cell: ({ row }) => (
        <div className="flex justify-start space-x-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => {
              showLog(row, LogTabs.FILE_LOGS);
            }}
          >
            <Eye />
          </Button>
        </div>
      ),
    },
  ];

  return columns;
};

export const getDatasetLogsTableColumns = (
  t: TFunction<'translation', string>,
  showLog: (row: Row<IFileLogItem & DocumentLog>, active: LogTabs) => void,
) => {
  // const { t } = useTranslate('knowledgeDetails');
  const columns: ColumnDef<IFileLogItem & DocumentLog>[] = [
    // {
    // id: 'select',
    // header: ({ table }) => (
    //   <input
    //     type="checkbox"
    //     checked={table.getIsAllRowsSelected()}
    //     onChange={table.getToggleAllRowsSelectedHandler()}
    //     className="rounded bg-gray-900 text-blue-500 focus:ring-blue-500"
    //   />
    // ),
    // cell: ({ row }) => (
    //   <input
    //     type="checkbox"
    //     checked={row.getIsSelected()}
    //     onChange={row.getToggleSelectedHandler()}
    //     className="rounded border-gray-600 bg-gray-900 text-blue-500 focus:ring-blue-500"
    //   />
    // ),
    // },
    {
      accessorKey: 'id',
      header: 'ID',
      meta: { headerCellClassName: LogColumnWidth.id },
      cell: ({ row }) => (
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="min-w-0 truncate text-text-primary">
              {row.original.id}
            </div>
          </TooltipTrigger>
          <TooltipContent>
            <p>{row.original.id}</p>
          </TooltipContent>
        </Tooltip>
      ),
    },
    {
      accessorKey: 'process_begin_at',
      header: ({ column }) => {
        return (
          <div className="flex items-center gap-1">
            {t('startDate')}
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={() =>
                column.toggleSorting(column.getIsSorted() === 'asc')
              }
            >
              <ArrowUpDown className="size-[1em]" />
            </Button>
          </div>
        );
      },
      meta: { headerCellClassName: LogColumnWidth.startDate },
      cell: ({ row }) => (
        <div className="text-text-primary">
          {formatDate(row.original.process_begin_at)}
        </div>
      ),
    },
    {
      accessorKey: 'task_type',
      header: t('processingType'),
      meta: { headerCellClassName: LogColumnWidth.task },
      cell: ({ row }) => (
        <div className="flex min-w-0 items-center gap-2 text-text-primary">
          {(ProcessingType.knowledgeGraph === row.original.task_type ||
            row.original.task_type === 'GraphRAG') && (
            <IconFontFill
              name={`knowledgegraph`}
              className="shrink-0 text-text-secondary"
            ></IconFontFill>
          )}
          {ProcessingType.raptor === row.original.task_type && (
            <IconFontFill
              name={`dataflow-01`}
              className="shrink-0 text-text-secondary"
            ></IconFontFill>
          )}
          <span className="truncate">
            {ProcessingTypeMap[row.original.task_type as ProcessingType] ||
              row.original.task_type}
          </span>
        </div>
      ),
    },
    {
      accessorKey: 'operation_status',
      header: t('status'),
      meta: { headerCellClassName: LogColumnWidth.status },
      cell: ({ row }) => (
        <FileStatusBadge
          status={row.original.operation_status as RunningStatus}
          name={
            RunningStatusMap[row.original.operation_status as RunningStatus]
          }
        />
      ),
    },
    {
      id: 'operations',
      header: t('operations'),
      meta: { headerCellClassName: LogColumnWidth.operations },
      cell: ({ row }) => (
        <div className="flex justify-start space-x-2 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => {
              showLog(row, LogTabs.DATASET_LOGS);
            }}
          >
            <Eye />
          </Button>
        </div>
      ),
    },
  ];

  return columns;
};

const FileLogsTable: FC<FileLogsTableProps> = ({
  data,
  pagination,
  setPagination,
  loading,
  active = LogTabs.FILE_LOGS,
}) => {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [rowSelection, setRowSelection] = useState({});
  const { t } = useTranslate('knowledgeDetails');
  const { t: tDatasetOverview } = useTranslate('datasetOverview');
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [logInfo, setLogInfo] = useState<IFileLogItem>();
  const showLog = (row: Row<IFileLogItem & DocumentLog>) => {
    const logDetail = {
      taskId: row.original?.dsl?.task_id,
      fileName: row.original.document_name,
      source: row.original.source_from,
      task: row.original?.task_type,
      status: row.original.status as RunningStatus,
      startDate: formatDate(row.original.process_begin_at),
      duration: formatSecondsToHumanReadable(
        row.original.process_duration || 0,
      ),
      details: row.original.progress_msg,
    } as unknown as IFileLogItem;
    setLogInfo(logDetail);
    setIsModalVisible(true);
  };
  const { dataSourceInfo } = useDataSourceInfo();
  const columns = useMemo(() => {
    return active === LogTabs.FILE_LOGS
      ? getFileLogsTableColumns(t, showLog, dataSourceInfo)
      : getDatasetLogsTableColumns(t, showLog);
  }, [active, t]);

  const currentPagination = useMemo(
    () => ({
      pageIndex: (pagination.current || 1) - 1,
      pageSize: pagination.pageSize || 10,
    }),
    [pagination],
  );

  const table = useReactTable<IFileLogItem & DocumentLog>({
    data: data || [],
    columns,
    manualPagination: true,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onRowSelectionChange: setRowSelection,
    state: {
      sorting,
      columnFilters,
      rowSelection,
      pagination: currentPagination,
    },
    pageCount: pagination.total
      ? Math.ceil(pagination.total / pagination.pageSize)
      : 0,
  });

  return (
    /* This box is the page's list region: it holds the table and the pager and
       nothing else, so the page size is what the ROWS can show.

       It used to be the whole sub-page scroller (the dataset shell marks one, and
       nothing here marked a tighter box), which made the measurement subtract
       everything above the table - the card's padding, the statistics cards and
       the filter bar - and re-measure whenever any of it moved. On the live page
       that read `page_size` 50, 7, 6, 13 in one load, and at 1280x700 with the
       sidebar open the remainder fell under the trustworthy minimum, so the page
       fell back to the 50 cap: the "50 条/页" the report names. Measuring the rows'
       own box removes every one of those terms. */
    <div
      className="flex min-h-0 w-full flex-1 flex-col overflow-auto"
      data-list-region=""
      data-list-item-height={TABLE_ROW_PITCH_PX}
    >
      <Table
        rootClassName="min-h-0 flex-1"
        className="table-fixed [&_td]:overflow-hidden [&_td]:py-0 [&_td]:whitespace-nowrap [&_th]:overflow-hidden [&_th]:whitespace-nowrap"
      >
        <TableHeader className="bg-table-header [&_tr]:border-b [&_tr]:border-table-border">
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow
              key={headerGroup.id}
              className="border-b border-table-border hover:bg-table-header"
            >
              {headerGroup.headers.map((header) => (
                <TableHead
                  key={header.id}
                  className={cn(
                    LogHeadCellClass,
                    header.column.columnDef.meta?.headerCellClassName,
                  )}
                >
                  {flexRender(
                    header.column.columnDef.header,
                    header.getContext(),
                  )}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows?.length ? (
            table.getRowModel().rows.map((row) => (
              <TableRow
                key={row.id}
                data-state={row.getIsSelected() && 'selected'}
                className={LogRowClass}
              >
                {row.getVisibleCells().map((cell) => (
                  <TableCell
                    key={cell.id}
                    className={cell.column.columnDef.meta?.cellClassName}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : loading ? (
            /* A read in flight is not an empty list. Without this the first paint
               said "no data" for as long as the request took and then turned into
               rows - a visible jump under a summary that had already settled.
               `TableSkeleton` carries `data-skeleton`, so it is the same 96px the
               empty row is and neither counts as row space. */
            <TableSkeleton columnsLength={columns.length} />
          ) : (
            /* `data-skeleton`: this row is not data - it is 96px against a 38px
               log row, and the page size is derived from a row's height, so a
               measurement taken while the logs are empty would page the table by
               a third of what it can show. */
            <TableRow data-skeleton="">
              <TableCell colSpan={columns.length} className="h-24 text-center">
                <Empty
                  type={EmptyType.Data}
                  text={tDatasetOverview('noData')}
                />
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      {/* `data-list-footer` is what tells the measurement to subtract the pager:
          the capacity is the space the ROWS have, not the space the box has. The
          pager is always rendered here (it has no data-dependent branch), so its
          row is part of the layout from the first paint. */}
      <footer
        data-list-footer=""
        className="flex shrink-0 items-center justify-end pt-4"
      >
        <RAGFlowPagination
          {...{ current: pagination.current, pageSize: pagination.pageSize }}
          total={pagination.total}
          /* No size selector on this page: its page size is not a preference, it
             is the number of log rows this viewport's list region can hold, and
             the region re-measures itself on every resize and sidebar toggle.
             An offer of "10 / 20 / 50" would be an offer the page cannot honour -
             a size larger than the region is a scrollbar inside the table. The
             pager keeps the count, the pages and the prev/next controls. */
          showSizeChanger={false}
          onChange={(page, pageSize) => setPagination({ page, pageSize })}
        />
      </footer>

      {isModalVisible && (
        <ProcessLogModal
          title={active === LogTabs.FILE_LOGS ? t('fileLogs') : t('datasetLog')}
          visible={isModalVisible}
          onCancel={() => setIsModalVisible(false)}
          logInfo={logInfo as unknown as ILogInfo}
        />
      )}
    </div>
  );
};

export default FileLogsTable;
