import { DatasetCategory, resolveDatasetCategory } from '@/constants/dataset-category';
import { IDataset } from '@/interfaces/database/dataset';
import dayjs from 'dayjs';
import { useCallback, useState } from 'react';

/** Sentinel for "every class"; kept out of the enum so `category` stays a string. */
export const AllDatasetCategories = 'all';

export type DatasetQuery = {
  category: string;
  keyword: string;
  /** Inclusive lower bound on the knowledge base's creation date. */
  createdFrom?: Date;
  /** Inclusive upper bound, widened to the end of that day. */
  createdTo?: Date;
};

const InitialDatasetQuery: DatasetQuery = {
  category: AllDatasetCategories,
  keyword: '',
};

/**
 * The 检索条件 panel's state and the filter it drives.
 *
 * Filtering is local to the list already on screen: the panel narrows what the
 * operator sees without firing another request per keystroke, and 重置 restores
 * the full list. The knowledge base count on these pages is a single page, so a
 * round trip would only add latency.
 */
export function useDatasetQuery() {
  const [query, setQuery] = useState<DatasetQuery>(InitialDatasetQuery);

  const setCategory = useCallback((category: string) => {
    setQuery((prev) => ({ ...prev, category }));
  }, []);

  const setKeyword = useCallback((keyword: string) => {
    setQuery((prev) => ({ ...prev, keyword }));
  }, []);

  const setCreatedFrom = useCallback((createdFrom?: Date) => {
    setQuery((prev) => ({ ...prev, createdFrom }));
  }, []);

  const setCreatedTo = useCallback((createdTo?: Date) => {
    setQuery((prev) => ({ ...prev, createdTo }));
  }, []);

  const reset = useCallback(() => setQuery(InitialDatasetQuery), []);

  const filter = useCallback(
    (datasets: IDataset[]) => {
      const keyword = query.keyword.trim().toLowerCase();
      const from = query.createdFrom
        ? dayjs(query.createdFrom).startOf('day')
        : undefined;
      const to = query.createdTo
        ? dayjs(query.createdTo).endOf('day')
        : undefined;

      return datasets.filter((dataset) => {
        if (
          query.category !== AllDatasetCategories &&
          resolveDatasetCategory(dataset).category !==
            (query.category as DatasetCategory)
        ) {
          return false;
        }

        if (keyword) {
          const haystack = `${dataset.name ?? ''} ${
            dataset.description ?? ''
          }`.toLowerCase();
          if (!haystack.includes(keyword)) {
            return false;
          }
        }

        const created = dayjs(dataset.create_time);
        if (from && created.isBefore(from)) {
          return false;
        }
        if (to && created.isAfter(to)) {
          return false;
        }

        return true;
      });
    },
    [query],
  );

  const isFiltered =
    query.category !== AllDatasetCategories ||
    query.keyword.trim() !== '' ||
    Boolean(query.createdFrom) ||
    Boolean(query.createdTo);

  return {
    query,
    isFiltered,
    setCategory,
    setKeyword,
    setCreatedFrom,
    setCreatedTo,
    reset,
    filter,
  };
}
