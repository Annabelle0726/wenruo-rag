import { FilterCollection } from '@/components/list-filter-bar/interface';
import SvgIcon from '@/components/svg-icon';
import { useIsDarkTheme } from '@/components/theme-provider';

import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
} from '@/components/ui/card';

import WhatIsThis from '@/components/what-is-this';
import { RunningStatusMap, RunningStatusOld } from '@/constants/knowledge';
import { useFetchDocumentList } from '@/hooks/use-document-request';
import { FC, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { RunningStatus } from '../dataset/constant';
import { LogTabs } from './dataset-common';
import { DatasetFilter } from './dataset-filter';
import { useFetchFileLogList, useFetchOverviewTotal } from './hook';
import { DocumentLog, IFileLogItem } from './interface';
import FileLogsTable from './overview-table';

interface StatCardProps {
  title: string;
  value: number;
  icon: JSX.Element;
  children?: JSX.Element;
  tooltip?: string;
}
interface CardFooterProcessProps {
  success: number;
  failed: number;
  successTip?: string;
  failedTip?: string;
}

/**
 * One row of the page summary: a strip, not a hero.
 *
 * The three modules keep everything they said before - the same label, the same
 * number, the same tooltip and the same detail line underneath - but they are laid
 * out as identity on the left (icon, label, value) and detail under it, so the
 * whole block is one 66px strip instead of a 116px card. The page's subject is the
 * log table below; the summary states four numbers and gets out of its way. It is
 * also why the number is 18px rather than 24px: still the largest figure in the
 * card, no longer competing with the table's header for attention.
 */
const StatCard: FC<StatCardProps> = ({
  title,
  value,
  children,
  icon,
  tooltip,
}) => {
  return (
    <Card className="flex items-center gap-3 rounded-lg border-border-default px-3.5 py-2">
      <span className="flex size-8 shrink-0 items-center justify-center">
        {icon}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <CardHeader className="min-w-0 p-0">
            <h3 className="flex min-w-0 items-center gap-1 text-xs font-medium text-text-secondary">
              <span className="truncate">{title}</span>

              {tooltip && <WhatIsThis>{tooltip}</WhatIsThis>}
            </h3>
          </CardHeader>

          <CardDescription className="shrink-0 text-lg leading-6 font-semibold text-text-primary tabular-nums">
            <data value={value}>{value}</data>
          </CardDescription>
        </div>

        <CardFooter className="mt-1 flex w-full items-center p-0">
          <div className="min-w-0 flex-1">{children}</div>
        </CardFooter>
      </div>
    </Card>
  );
};

/**
 * The success/failed split, as one line of two chips.
 *
 * Same two figures, same colours (`--state-success-5` / `--state-error-5`) and the
 * same dot markers; the fill is now a 20px chip around them instead of a padded
 * panel, which is one of the things that lets the card above close at 66px.
 */
const CardFooterProcess: FC<CardFooterProcessProps> = ({
  success = 0,
  successTip,
  failed = 0,
  failedTip,
}) => {
  const { t } = useTranslation();

  return (
    <dl className="flex w-full items-center gap-2 text-xs">
      <div className="flex min-w-0 flex-1 items-center justify-between gap-1 rounded-sm bg-state-success-5 px-1.5 py-0.5">
        <dt className="flex min-w-0 items-center gap-1 text-text-secondary">
          <span className="size-1 shrink-0 rounded-full bg-state-success" />
          <span className="truncate">{t('knowledgeDetails.success')}</span>
          {successTip && <WhatIsThis>{successTip}</WhatIsThis>}
        </dt>

        <dd className="shrink-0 font-medium text-text-primary tabular-nums">
          {success || 0}
        </dd>
      </div>

      <div className="flex min-w-0 flex-1 items-center justify-between gap-1 rounded-sm bg-state-error-5 px-1.5 py-0.5">
        <dt className="flex min-w-0 items-center gap-1 text-text-secondary">
          <span className="size-1 shrink-0 rounded-full bg-state-error" />
          <span className="truncate">{t('knowledgeDetails.failed')}</span>
          {failedTip && <WhatIsThis>{failedTip}</WhatIsThis>}
        </dt>

        <dd className="shrink-0 font-medium text-text-primary tabular-nums">
          {failed || 0}
        </dd>
      </div>
    </dl>
  );
};

const FileLogsPage: FC = () => {
  const { t } = useTranslation();

  const [topAllData, setTopAllData] = useState({
    totalFiles: {
      value: 0,
      precent: 0,
    },
    downloads: {
      value: 0,
      success: 0,
      failed: 0,
    },
    processing: {
      value: 0,
      success: 0,
      failed: 0,
    },
  });
  const { data: topData } = useFetchOverviewTotal();
  const {
    pagination: { total: fileTotal },
    // The page shows this number and nothing else from the document list, so the
    // request must not go out before the log table's region has been read: with no
    // size to ask for it would fetch the 50-record cap and then fetch again.
  } = useFetchDocumentList(false, { countOnly: true });

  useEffect(() => {
    setTopAllData((prev) => {
      return {
        ...prev,
        downloads: {
          ...prev.downloads,
          success: topData?.downloaded || 0,
        },
        processing: {
          value: topData?.processing || 0,
          success: topData?.finished || 0,
          failed: topData?.failed || 0,
        },
      };
    });
  }, [topData]);

  useEffect(() => {
    setTopAllData((prev) => {
      return {
        ...prev,
        totalFiles: {
          value: fileTotal || 0,
          precent: 0,
        },
      };
    });
  }, [fileTotal]);

  const {
    data: tableOriginData,
    loading: tableLoading,
    searchString,
    handleInputChange,
    pagination,
    setPagination,
    active,
    filterValue,
    setFilterValue,
    handleFilterSubmit,
    setActive,
  } = useFetchFileLogList();

  const filters = useMemo(() => {
    const filterCollection: FilterCollection[] = [
      {
        field: 'operation_status',
        label: t('knowledgeDetails.status'),
        list: Object.values(RunningStatusOld).map((value) => {
          // const value = key as RunningStatus;
          return {
            id: value,
            // label: RunningStatusMap[value].label,
            label: RunningStatusMap[value],
          };
        }),
      },
      // {
      //   field: 'types',
      //   label: t('knowledgeDetails.task'),
      //   list: [
      //     {
      //       id: 'Parse',
      //       label: 'Parse',
      //     },
      //     {
      //       id: 'Download',
      //       label: 'Download',
      //     },
      //   ],
      // },
    ];
    if (active === LogTabs.FILE_LOGS) {
      return filterCollection;
    }
    if (active === LogTabs.DATASET_LOGS) {
      const list = filterCollection.filter((item, index) => index === 0);
      return list;
    }
    return [];
  }, [active, t]);

  const tableList = useMemo(() => {
    if (tableOriginData && tableOriginData.logs?.length) {
      return tableOriginData.logs.map((item) => {
        return {
          ...item,
          status: item.operation_status as RunningStatus,
          statusName: RunningStatusMap[item.operation_status as RunningStatus],
        } as unknown as IFileLogItem & DocumentLog;
      });
    }
    return [];
  }, [tableOriginData]);

  const changeActiveLogs = (active: (typeof LogTabs)[keyof typeof LogTabs]) => {
    setFilterValue({});
    setActive(active);
  };
  const handlePaginationChange = ({
    page,
    pageSize,
  }: {
    page: number;
    pageSize: number;
  }) => {
    setPagination({
      ...pagination,
      page,
      pageSize: pageSize,
    });
  };

  const isDark = useIsDarkTheme();

  return (
    /* A flex column with a definite height, so the log table's region can take
       what is left after the statistics and the filter: that region is the box the
       page size is measured from. `min-w-[880px]` and the page's own scrollbar are
       both gone - a width floor there pushed a horizontal scrollbar onto the page
       at narrower widths, which is the squeeze the report describes, and a second
       scroller inside the shell's own scroller could only fight it. */
    <Card
      className="
      p-5 mr-5 mb-5 bg-transparent shadow-none
      flex h-full min-h-0 flex-col"
    >
      {/* Stats Cards. `gap-4 mb-4`, not `gap-7 mb-6`: the row is a summary strip
          above the page's real subject, and every pixel it does not spend is a
          pixel the table region can show a log row in. */}
      <div className="grid shrink-0 grid-cols-3 gap-4 mb-4">
        <StatCard
          title={t('datasetOverview.totalFiles')}
          value={topAllData.totalFiles.value}
          icon={
            isDark ? (
              <SvgIcon name="data-flow/total-files-icon" width={24} />
            ) : (
              <SvgIcon name="data-flow/total-files-icon-bri" width={24} />
            )
          }
        >
          <div className="text-xs">
            <span className="text-accent-primary">
              {topAllData.totalFiles.precent > 0 ? '+' : ''}
              {topAllData.totalFiles.precent}%{' '}
            </span>
            <span className="font-normal text-text-secondary">
              {t('knowledgeConfiguration.lastWeek')}
            </span>
          </div>
        </StatCard>
        <StatCard
          title={t('datasetOverview.downloading')}
          value={topAllData.downloads.value}
          icon={
            isDark ? (
              <SvgIcon name="data-flow/data-icon" width={24} />
            ) : (
              <SvgIcon name="data-flow/data-icon-bri" width={24} />
            )
          }
          tooltip={t('datasetOverview.downloadTip')}
        >
          <CardFooterProcess
            success={topAllData.downloads.success}
            successTip={t('datasetOverview.downloadSuccessTip')}
            failed={topAllData.downloads.failed}
            failedTip={t('datasetOverview.downloadFailedTip')}
          />
        </StatCard>
        <StatCard
          title={t('datasetOverview.processing')}
          value={topAllData.processing.value}
          icon={
            isDark ? (
              <SvgIcon name="data-flow/processing-icon" width={24} />
            ) : (
              <SvgIcon name="data-flow/processing-icon-bri" width={24} />
            )
          }
          tooltip={t('datasetOverview.processingTip')}
        >
          <CardFooterProcess
            success={topAllData.processing.success}
            successTip={t('datasetOverview.processingSuccessTip')}
            failed={topAllData.processing.failed}
            failedTip={t('datasetOverview.processingFailedTip')}
          />
        </StatCard>
      </div>

      {/* Tabs & Search. `shrink-0` so the flex column never squeezes the tab row
          or the search field to give the table more room - the table's region is
          the element that flexes. */}
      <div className="shrink-0">
        <DatasetFilter
          filters={filters as FilterCollection[]}
          value={filterValue}
          active={active}
          setActive={changeActiveLogs}
          searchString={searchString}
          onSearchChange={handleInputChange}
          onChange={handleFilterSubmit}
        />
      </div>

      {/* Table */}
      <FileLogsTable
        data={tableList}
        loading={tableLoading}
        pagination={pagination}
        setPagination={handlePaginationChange}
        pageCount={10}
        active={active}
      />
    </Card>
  );
};

export default FileLogsPage;
