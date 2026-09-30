'use client';

import {
  ColumnDef,
  ColumnFiltersState,
  SortingState,
  VisibilityState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { ArrowUpDown } from 'lucide-react';
import * as React from 'react';

import { FileIcon } from '@/components/icon-font';
import { RenameDialog } from '@/components/rename-dialog';
import { TableEmpty, TableSkeleton } from '@/components/table-skeleton';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { RAGFlowPagination } from '@/components/ui/ragflow-pagination';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { UseRowSelectionType } from '@/hooks/logic-hooks/use-row-selection';
import { useFetchFileList } from '@/hooks/use-file-request';
import { IFile } from '@/interfaces/database/file-manager';
import { formatFileSize } from '@/utils/common-util';
import { formatDate } from '@/utils/date';
import { pick } from 'lodash';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import {
  UseHandleConnectToKnowledgeReturnType,
  useRenameCurrentFile,
} from './hooks';
import { KnowledgeCell } from './knowledge-cell';
import { LinkToDatasetDialog } from './link-to-dataset-dialog';
import { useNavigateToOtherFolder } from './use-navigate-to-folder';
import { isFolderType, isKnowledgeBaseType } from './util';
import { useIsGoBackend } from '../../utils/backend-variant';

type FilesTableProps = Pick<
  ReturnType<typeof useFetchFileList>,
  'files' | 'loading' | 'pagination' | 'setPagination' | 'total'
> &
  Pick<UseRowSelectionType, 'rowSelection' | 'setRowSelection'> & {
    connectKnowledgeModal: UseHandleConnectToKnowledgeReturnType;
  };

export function FilesTable({
  files,
  total,
  pagination,
  setPagination,
  loading,
  rowSelection,
  setRowSelection,
  connectKnowledgeModal,
}: FilesTableProps) {
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>(
    [],
  );
  const [columnVisibility, setColumnVisibility] =
    React.useState<VisibilityState>({});
  const { t } = useTranslation('translation', {
    keyPrefix: 'fileManager',
  });
  const navigateToOtherFolder = useNavigateToOtherFolder();
  const navigate = useNavigate();
  const {
    connectToKnowledgeVisible,
    hideConnectToKnowledgeModal,
    initialConnectedIds,
    onConnectToKnowledgeOk,
    connectToKnowledgeLoading,
  } = connectKnowledgeModal;
  const {
    fileRenameVisible,
    hideFileRenameModal,
    onFileRenameOk,
    initialFileName,
    fileRenameLoading,
  } = useRenameCurrentFile();

  // Skills are only served by the Go backend
  const isSkillsEnabled = useIsGoBackend();

  // Sort files with the Go skills folder first, then by time
  const sortedFiles = useMemo(() => {
    if (!files) return [];

    return [...files].sort((a, b) => {
      const aIsSkills =
        isSkillsEnabled &&
        isFolderType(a.type) &&
        a.name.toLowerCase() === 'skills';
      const bIsSkills =
        isSkillsEnabled &&
        isFolderType(b.type) &&
        b.name.toLowerCase() === 'skills';

      // Skills folder always comes first
      if (aIsSkills && !bIsSkills) return -1;
      if (!aIsSkills && bIsSkills) return 1;

      // Then sort by create_time desc (newest first)
      return (b.create_time || 0) - (a.create_time || 0);
    });
  }, [files, isSkillsEnabled]);

  const columns: ColumnDef<IFile>[] = [
    {
      id: 'select',
      header: ({ table }) => (
        <Checkbox
          checked={
            table.getIsAllPageRowsSelected() ||
            (table.getIsSomePageRowsSelected() && 'indeterminate')
          }
          onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
          aria-label="Select all"
          className="rounded-md border-cable-border-hover shadow-ceramic data-[state=checked]:border-cable-accent data-[state=checked]:bg-cable-accent"
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          checked={row.getIsSelected()}
          onCheckedChange={(value) => row.toggleSelected(!!value)}
          aria-label="Select row"
          className="rounded-md border-cable-border-hover shadow-ceramic data-[state=checked]:border-cable-accent data-[state=checked]:bg-cable-accent"
          disabled={!row.getCanSelect()}
        />
      ),
      enableSorting: false,
      enableHiding: false,
      meta: { headerCellClassName: 'w-[3.5rem]' },
    },
    {
      accessorKey: 'name',
      header: ({ column }) => {
        return (
          <div className="flex items-center gap-1">
            {t('name')}
            <Button
              size="icon-xs"
              variant="ghost"
              onClick={() =>
                column.toggleSorting(column.getIsSorted() === 'asc')
              }
            >
              <ArrowUpDown />
            </Button>
          </div>
        );
      },
      meta: {
        cellClassName: 'min-w-0 overflow-hidden',
      },
      cell: ({ row }) => {
        const name: string = row.getValue('name');
        const type = row.original.type;
        const id = row.original.id;
        const isFolder = isFolderType(type);
        const isSkillsFolder =
          isSkillsEnabled && isFolder && name.toLowerCase() === 'skills';

        const handleNameClick = () => {
          if (isSkillsFolder) {
            navigate('/files/skills');
          } else if (isFolder) {
            navigateToOtherFolder(id);
          }
        };

        return (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="static"
                onClick={handleNameClick}
                className="max-w-full p-0 flex justify-start gap-2 text-text-primary"
              >
                {/* Icon tile: the file or folder mark sits on its own 32px glass
                    base so the name column has a fixed left edge and the type is
                    readable at a glance. The shared FileIcon itself is untouched,
                    because other pages render it without a tile. */}
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-cable-border-hover bg-cable-nav-active-bg text-cable-accent">
                  <FileIcon
                    name={name}
                    type={isSkillsFolder ? 'skills' : type}
                  />
                </span>

                <span className="min-w-0 truncate">{name}</span>
              </Button>
            </TooltipTrigger>

            <TooltipContent>{name}</TooltipContent>
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
      meta: { headerCellClassName: 'w-[11rem]' },
      cell: ({ row }) => (
        <div className="lowercase">
          {formatDate(row.getValue('create_time'))}
        </div>
      ),
    },
    {
      accessorKey: 'size',
      header: ({ column }) => {
        return (
          <div className="flex items-center gap-1">
            {t('size')}
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
      meta: { headerCellClassName: 'w-[6.5rem]' },
      cell: ({ row }) => (
        <div className="capitalize">{formatFileSize(row.getValue('size'))}</div>
      ),
    },
    {
      accessorKey: 'kbs_info',
      header: t('knowledgeBase'),
      cell: ({ row }) => {
        const value: IFile['kbs_info'] = row.getValue('kbs_info');
        return <KnowledgeCell value={value}></KnowledgeCell>;
      },
    },
  ];

  const currentPagination = useMemo(() => {
    return {
      pageIndex: (pagination.current || 1) - 1,
      pageSize: pagination.pageSize || 10,
    };
  }, [pagination]);

  const table = useReactTable({
    data: sortedFiles,
    columns,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    getCoreRowModel: getCoreRowModel(),
    // getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    onColumnVisibilityChange: setColumnVisibility,
    onRowSelectionChange: setRowSelection,
    getRowId: (row) => row.id, // Use file ID instead of row index
    manualPagination: true, //we're doing manual "server-side" pagination
    enableRowSelection(row) {
      const name = row.original.name;
      const type = row.original.type;
      const isSkillsFolder =
        isSkillsEnabled &&
        isFolderType(type) &&
        name.toLowerCase() === 'skills';
      // The Go skills folder is not selectable because it's a special entry.
      return !isKnowledgeBaseType(row.original.source_type) && !isSkillsFolder;
    },
    state: {
      sorting,
      columnFilters,
      columnVisibility,
      rowSelection,
      pagination: currentPagination,
    },
    rowCount: total ?? 0,
    debugTable: true,
  });

  return (
    <>
      {/* One glass shell for the whole table: a clean translucent pane so the
          rows stay the only thing to read. An earlier pass laid a CAD ruling
          under them, which fought the data instead of framing it. */}
      {/* The scrolling region is this box, which is already `flex-1 min-h-0`
          inside the page column: the table fills it and the page size is derived
          from how many complete rows it holds, so the table body must not carry a
          scroll cap of its own - a fixed `max-h-96` body scrolled internally even
          when the region had room for every row.

          The arbitrary variants are this table's geometry contract: 38px rows
          (`h-[38px]` below, with the cells' vertical padding taken out) that never
          wrap, so a row is the same height whatever width the region has. A
          wrapped cell is two lines tall, and the page size is derived from the row
          height - which is how a narrower region used to cost rows. */}
      <div className="glass-surface flex-1 min-h-0 size-full overflow-hidden rounded-2xl border border-cable-hairline">
        <Table
          rootClassName="max-h-full overflow-auto rounded-2xl bg-transparent"
          /* Header labels share one spec across every column: metadata size,
             medium weight, secondary ink. The sort arrow hover is declared here
             rather than on each Button because the ghost variant's own
             hover:text-text-primary competes at equal specificity — the
             descendant selector is what reliably wins. */
          className="[&_td]:py-0 [&_td]:whitespace-nowrap [&_th]:whitespace-nowrap [&_th]:text-sm [&_th]:font-medium [&_th]:text-text-primary [&_th_button:hover]:text-cable-accent [&_th_button_svg]:transition-colors [&_th_button_svg]:duration-200"
        >
          <TableHeader className="bg-table-header">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow
                key={headerGroup.id}
                className="border-b border-cable-hairline hover:bg-transparent"
              >
                {headerGroup.headers.map((header) => {
                  return (
                    <TableHead
                      key={header.id}
                      className={
                        header.column.columnDef.meta?.headerCellClassName
                      }
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
          <TableBody>
            {loading ? (
              <TableSkeleton columnsLength={columns.length}></TableSkeleton>
            ) : table.getRowModel().rows?.length ? (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  data-state={row.getIsSelected() && 'selected'}
                  className="group h-[38px] border-b border-cable-hairline bg-transparent transition-colors duration-200 hover:bg-table-row-hover data-[state=selected]:bg-table-row-hover"
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell
                      key={cell.id}
                      className={cell.column.columnDef.meta?.cellClassName}
                    >
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext(),
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableEmpty columnsLength={columns.length}></TableEmpty>
            )}
          </TableBody>
        </Table>
      </div>

      {/* `data-list-footer` is what tells the page-size measurement to subtract
          the pager: the capacity is the space the ROWS have, not the space the
          box has, and a pager counted as row space is a row the region cannot
          show. */}
      <footer
        data-list-footer=""
        className="flex shrink-0 items-center justify-end pb-5 mt-4"
      >
        <RAGFlowPagination
          {...pick(pagination, 'current', 'pageSize')}
          total={total}
          onChange={(page, pageSize) => {
            setPagination({ page, pageSize });
          }}
        />
      </footer>

      {connectToKnowledgeVisible && (
        <LinkToDatasetDialog
          hideModal={hideConnectToKnowledgeModal}
          initialConnectedIds={initialConnectedIds}
          onConnectToKnowledgeOk={onConnectToKnowledgeOk}
          loading={connectToKnowledgeLoading}
        ></LinkToDatasetDialog>
      )}
      {fileRenameVisible && (
        <RenameDialog
          hideModal={hideFileRenameModal}
          onOk={onFileRenameOk}
          initialName={initialFileName}
          loading={fileRenameLoading}
          forbidSlash
        ></RenameDialog>
      )}
    </>
  );
}
