'use client';

import {
  ColumnFiltersState,
  SortingState,
  VisibilityState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import * as React from 'react';

import { cn } from '@/lib/utils';
import { PAGER_ROW_HEIGHT_PX } from '@/utils/list-capacity';
import { EmptyType } from '@/components/empty/constant';
import Empty from '@/components/empty/empty';
import { LoadingDots } from '@/components/loading-dots';
import { RenameDialog } from '@/components/rename-dialog';
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
import { UseRowSelectionType } from '@/hooks/logic-hooks/use-row-selection';
import { documentListIsSettled } from '@/hooks/document-list-state';
import { useFetchDocumentList } from '@/hooks/use-document-request';
import { t } from 'i18next';
import { pick } from 'lodash';
import { useMemo } from 'react';
import { ShowManageMetadataModalProps } from '../components/metedata/interface';
import ProcessLogModal from '../process-log-modal';
import { ChangeParserDialog } from './change-parser-dialog';
import { useShowLog } from './hooks';
import { useChangeDocumentParser } from './use-change-document-parser';
import { useDocumentVisibility } from './use-document-visibility';
import { useDatasetTableColumns } from './use-dataset-table-columns';
import { useRenameDocument } from './use-rename-document';

export type DatasetTableProps = Pick<
  ReturnType<typeof useFetchDocumentList>,
  'documents' | 'setPagination' | 'pagination' | 'state' | 'retry'
> &
  Pick<UseRowSelectionType, 'rowSelection' | 'setRowSelection'> & {
    showManageMetadataModal: (config: ShowManageMetadataModalProps) => void;
    /**
     * The bulk bar used to change this table's maximum height (and so its own
     * internal scrollbar). The table no longer caps its own height - the page's
     * region does, and the page size is derived from that region - so the flag is
     * kept only so callers keep compiling; it no longer affects the layout.
     */
    bulkOperateBarVisible?: boolean;
  };

export function DatasetTable({
  documents,
  pagination,
  setPagination,
  state,
  retry,
  rowSelection,
  setRowSelection,
  showManageMetadataModal,
}: DatasetTableProps) {
  const { isDocumentHidden } = useDocumentVisibility();
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>(
    [],
  );
  const [columnVisibility, setColumnVisibility] =
    React.useState<VisibilityState>({});

  const {
    changeParserLoading,
    onChangeParserOk,
    changeParserVisible,
    hideChangeParserModal,
    showChangeParserModal,
    changeParserRecord,
  } = useChangeDocumentParser();

  const {
    renameLoading,
    onRenameOk,
    renameVisible,
    hideRenameModal,
    showRenameModal,
    initialName,
  } = useRenameDocument();

  const { showLog, logInfo, logVisible, hideLog } = useShowLog(documents);

  const columns = useDatasetTableColumns({
    showChangeParserModal,
    showRenameModal,
    showManageMetadataModal,
    showLog,
    setRowSelection,
  });

  const currentPagination = useMemo(() => {
    return {
      pageIndex: (pagination.current || 1) - 1,
      pageSize: pagination.pageSize || 10,
    };
  }, [pagination]);

  // Only a settled, successful read may report on the list's contents. A read
  // that is loading, refused or failed has no rows *and no count*: rendering
  // "暂无数据 / 共 0 条" for it states a fact nobody established.
  const settled = documentListIsSettled(state);

  const table = useReactTable({
    data: documents,
    columns,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    onColumnVisibilityChange: setColumnVisibility,
    onRowSelectionChange: setRowSelection,
    getRowId: (row) => row.id, // Use document ID instead of row index
    manualPagination: true, //we're doing manual "server-side" pagination
    state: {
      sorting,
      columnFilters,
      columnVisibility,
      rowSelection,
      pagination: currentPagination,
    },
    rowCount: pagination.total ?? 0,
  });

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col">
      {/* No `max-h-[calc(100vh-…)]` here: the viewport is the shell's business
          (`#root` is `100dvh` and `main` is the row under the breadcrumb), so a
          second viewport-relative cap on the table guessed at space the page had
          already accounted for and gave the body a scrollbar of its own - with
          six rows on screen and room for all six. The page's own region holds the
          table and pages it by complete rows instead.

          `table-fixed` plus the column widths in `DocumentColumnWidth` is what
          makes this table behave. In the default auto layout a column's minimum
          width comes from its CONTENT, and a file name is one unbreakable run under
          `whitespace-nowrap` - so the name column alone demanded 422px and the
          table could not shrink below 1218px inside a 1116px box: it overflowed by
          102px and threw a horizontal scrollbar at a normal desktop width. Fixed
          layout sizes the columns from their declared widths and gives the one
          column without a width (the name) whatever is left, so the table is
          exactly as wide as its box, the columns never move with the content, and
          a long name ellipsizes instead of pushing the row wider.

          The three arbitrary variants are the other half of the contract: rows are
          exactly 38px (`h-[38px]` below, with the vertical padding taken out of the
          cells), no cell may wrap, and a cell whose content does not fit is
          clipped rather than drawn over its neighbour. */}
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
              {headerGroup.headers.map((header) => {
                return (
                  <TableHead
                    key={header.id}
                    className={cn(
                      'h-10 text-[13px] font-semibold text-table-head-ink',
                      header.column.columnDef.meta?.headerCellClassName,
                    )}
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                  </TableHead>
                );
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody className="relative">
          {table.getRowModel().rows?.length ? (
            table.getRowModel().rows.map((row) => (
              <TableRow
                key={row.id}
                data-testid="document-row"
                data-doc-name={row.original.name}
                data-state={row.getIsSelected() && 'selected'}
                className={cn(
                  'group h-[38px] border-b border-table-border hover:bg-table-row-hover data-[state=selected]:bg-table-row-hover',
                  isDocumentHidden(row.original.status)
                    ? 'bg-status-archived text-text-secondary'
                    : 'odd:bg-table-row-base even:bg-table-row-alternate',
                )}
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
          ) : (
            // `data-skeleton` marks this row as NOT data: it is 96px against a
            // 38px document row, and the page size is derived from a row's height,
            // so measuring this one would page the table by a third of what it can
            // show - exactly while the list is loading or empty.
            <TableRow
              data-skeleton=""
              data-testid={`document-list-${state.status}`}
            >
              <TableCell colSpan={columns.length} className="h-24 text-center">
                {state.status === 'forbidden' ? (
                  <Empty
                    type={EmptyType.Data}
                    text={t('knowledgeDetails.filesForbidden')}
                  />
                ) : state.status === 'error' ? (
                  <div className="flex flex-col items-center justify-center gap-2">
                    <span className="text-text-secondary text-sm">
                      {t('knowledgeDetails.filesLoadFailed')}
                      {state.code === undefined ? '' : ` (code ${state.code})`}
                    </span>
                    <Button variant="outline" size="sm" onClick={retry}>
                      {t('common.retry')}
                    </Button>
                  </div>
                ) : settled ? (
                  <Empty type={EmptyType.Data} />
                ) : (
                  <div className="flex items-center justify-center gap-2">
                    <LoadingDots />
                    <span className="text-text-secondary text-sm">
                      {t('knowledgeDetails.filesLoading')}
                    </span>
                  </div>
                )}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      {/* The pager is a flex sibling AFTER the list region, in the page's own
          flow. It used to be `absolute bottom-3 right-8`, which took it out of
          the flow entirely: with no positioned ancestor it anchored to the
          viewport, floated over the last rows of the table, and contributed
          nothing to the height the page size is measured from - so the page asked
          for rows it then covered with the pager.

          Its ROW is reserved from the first paint, while the pager itself is
          rendered only once the list has an answer: a pager states a count, and
          there is no count to state while the read is in flight, refused or
          failed. Reserving the row is what keeps the page size still - measured
          without a pager the rows area reads one row taller, so the size moved the
          moment the data landed and the table reloaded itself around it. */}
      <footer
        data-list-footer=""
        className="flex shrink-0 items-center justify-end pt-4"
        style={{ minHeight: PAGER_ROW_HEIGHT_PX }}
      >
        {settled && (
          <RAGFlowPagination
            {...pick(pagination, 'current', 'pageSize')}
            total={pagination.total}
            onChange={(page, pageSize) => {
              setPagination({ page, pageSize });
            }}
          ></RAGFlowPagination>
        )}
      </footer>
      {changeParserVisible && (
        <ChangeParserDialog
          record={changeParserRecord}
          visible={changeParserVisible}
          onOk={onChangeParserOk}
          hideModal={hideChangeParserModal}
          loading={changeParserLoading}
        />
      )}

      {renameVisible && (
        <RenameDialog
          visible={renameVisible}
          onOk={onRenameOk}
          loading={renameLoading}
          hideModal={hideRenameModal}
          initialName={initialName}
        ></RenameDialog>
      )}

      {logVisible && (
        <ProcessLogModal
          title={t('knowledgeDetails.fileLogs')}
          visible={logVisible}
          onCancel={() => hideLog()}
          logInfo={logInfo}
        />
      )}
    </div>
  );
}
