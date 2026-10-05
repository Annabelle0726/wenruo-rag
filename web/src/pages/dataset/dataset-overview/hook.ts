import { useHandleFilterSubmit } from '@/components/list-filter-bar/use-handle-filter-submit';
import {
  useGetPaginationWithRouter,
  useHandleSearchChange,
} from '@/hooks/logic-hooks';
import {
  getKnowledgeBasicInfo,
  listDataPipelineLogDocument,
} from '@/services/knowledge-service';
import { useQuery } from '@tanstack/react-query';
import { useCallback, useState } from 'react';
import { useParams, useSearchParams } from 'react-router';
import { LogTabs } from './dataset-common';
import { IFileLogList, IOverviewTotal } from './interface';

const useFetchOverviewTotal = () => {
  const [searchParams] = useSearchParams();
  const { id } = useParams();
  const knowledgeBaseId = searchParams.get('id') || id;
  const { data } = useQuery<IOverviewTotal>({
    queryKey: ['overviewTotal'],
    queryFn: async () => {
      const { data: res = {} } = await getKnowledgeBasicInfo(
        knowledgeBaseId || '',
      );
      return res.data || [];
    },
  });
  return { data };
};

const useFetchFileLogList = () => {
  const [searchParams] = useSearchParams();
  const { searchString, handleInputChange } = useHandleSearchChange();
  const { pagination, setPagination, measured } = useGetPaginationWithRouter();
  const { filterValue, setFilterValue, handleFilterSubmit } =
    useHandleFilterSubmit();
  const { id } = useParams();
  const [active, setActive] = useState<(typeof LogTabs)[keyof typeof LogTabs]>(
    LogTabs.FILE_LOGS,
  );
  const knowledgeBaseId = searchParams.get('id') || id;
  const logType = active === LogTabs.DATASET_LOGS ? 'dataset' : 'file';
  const { data, isFetching, isPending } = useQuery<IFileLogList>({
    queryKey: [
      'fileLogList',
      knowledgeBaseId,
      pagination,
      searchString,
      active,
      filterValue,
    ],
    // The previous page's rows stay on screen while the next one is read, so a
    // page turn never blanks the table. On the FIRST load there is nothing to
    // carry over and deliberately no fabricated empty list: the table renders its
    // skeleton instead, which is the same height as the rows it becomes.
    placeholderData: (previousData) => previousData,
    // This page's one page size is the capacity of its list region, and that
    // reading is published by a pre-paint layout effect in the mounting commit -
    // so holding the first request until then costs no time at all and is what
    // keeps a default `page_size` (the 50 cap) out of the network log. It is not
    // a gate on the data: `measured` is true from the first commit, whether or
    // not a region was found, so it can never leave this table empty.
    enabled: measured,
    queryFn: async () => {
      const { data: res = {} } = await listDataPipelineLogDocument(
        knowledgeBaseId || '',
        {
          page: pagination.current,
          page_size: pagination.pageSize,
          keywords: searchString,
          log_type: logType,
          ...filterValue,
        },
      );
      return res.data || [];
    },
  });
  const onInputChange: React.ChangeEventHandler<HTMLInputElement> = useCallback(
    (e) => {
      setPagination({ page: 1 });
      handleInputChange(e);
    },
    [handleInputChange, setPagination],
  );
  return {
    data,
    // True until the first answer for the current region/size is on screen,
    // which is what the table shows its skeleton for.
    loading: isPending || isFetching,
    searchString,
    handleInputChange: onInputChange,
    pagination: { ...pagination, total: data?.total },
    setPagination,
    active,
    setActive,
    filterValue,
    setFilterValue,
    handleFilterSubmit,
  };
};

export { useFetchFileLogList, useFetchOverviewTotal };
