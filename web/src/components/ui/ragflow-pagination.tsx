import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from '@/components/ui/pagination';
import {
  SelectWithSearch,
  SelectWithSearchOptionType,
} from '@/components/originui/select-with-search';
import { currentListCapacity } from '@/hooks/use-list-capacity';
import { pageSizeOptionsFor } from '@/utils/list-capacity';
import { cn } from '@/lib/utils';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

export type RAGFlowPaginationType = {
  showQuickJumper?: boolean;
  onChange?(page: number, pageSize: number): void;
  total?: number;
  current?: number;
  pageSize?: number;
  showSizeChanger?: boolean;
  /**
   * The sizes the control may offer. A list page passes the sizes its own region
   * can honour (see `pageSizeOptionsFor`), so the control can never offer a size
   * the layout would not use. Whatever `pageSize` is, it is always offered too:
   * the control has to be able to show the size the page is really using, or the
   * two disagree.
   */
  sizeOptions?: number[];
};

/**
 * One page control. The whole pager and the page-size picker live inside a single
 * translucent capsule, so the row reads as one instrument rather than two loose
 * controls; the current page is a small ceramic tile lifted out of that capsule,
 * and every other page answers the pointer with a frosted sheen instead of a
 * filled block. Colours come from the theme tokens, so light and dark switch
 * without a `dark:` variant here.
 */
const PagerMotion =
  'transition-[background-color,border-color,color,box-shadow] duration-200 ease-in-out';
const PagerRestClass = cn(
  'size-8 rounded-lg text-content-secondary',
  PagerMotion,
  'hover:bg-cable-nav-active-bg hover:text-content-primary',
);
const PagerCurrentClass = cn(
  'size-8 rounded-lg border border-cable-hairline bg-glass text-content-primary shadow-ceramic',
  PagerMotion,
);

export function RAGFlowPagination({
  current = 1,
  pageSize = 5,
  total = 0,
  onChange,
  showSizeChanger = true,
  sizeOptions,
}: RAGFlowPaginationType) {
  const { t } = useTranslation();
  const [currentPage, setCurrentPage] = useState(1);
  const [currentPageSize, setCurrentPageSize] = useState('10');

  const offeredSizes = useMemo(() => {
    const values = new Set(
      sizeOptions?.length
        ? sizeOptions
        : pageSizeOptionsFor(currentListCapacity()),
    );
    // The effective size is always on the list, even when the page derived one
    // that is not a preset: the trigger shows the selected option, so a size with
    // no option would leave the control blank while the page paginated by it.
    if (pageSize) values.add(pageSize);
    return [...values].filter((value) => value > 0).sort((a, b) => a - b);
  }, [sizeOptions, pageSize]);

  const sizeChangerOptions: SelectWithSearchOptionType[] = useMemo(() => {
    return offeredSizes.map((x) => ({
      label: <span>{t('pagination.page', { size: x })}</span>,
      value: x.toString(),
    }));
  }, [offeredSizes, t]);

  const pages = useMemo(() => {
    const num = Math.ceil(total / pageSize);
    return new Array(num).fill(0).map((_, idx) => idx + 1);
  }, [pageSize, total]);

  const changePage = useCallback(
    (page: number) => {
      onChange?.(page, Number(currentPageSize));
    },
    [currentPageSize, onChange],
  );

  const handlePreviousPageChange = useCallback(() => {
    setCurrentPage((page) => {
      const previousPage = page - 1;
      if (previousPage > 0) {
        changePage(previousPage);
        return previousPage;
      }
      changePage(page);
      return page;
    });
  }, [changePage]);

  const handlePageChange = useCallback(
    (page: number) => () => {
      changePage(page);
      setCurrentPage(page);
    },
    [changePage],
  );

  const handleNextPageChange = useCallback(() => {
    setCurrentPage((page) => {
      const nextPage = page + 1;
      if (nextPage <= pages.length) {
        changePage(nextPage);
        return nextPage;
      }
      changePage(page);
      return page;
    });
  }, [changePage, pages.length]);

  const handlePageSizeChange = useCallback(
    (size: string) => {
      onChange?.(1, Number(size));
      setCurrentPageSize(size);
    },
    [onChange],
  );

  useEffect(() => {
    setCurrentPage(current);
  }, [current]);

  useEffect(() => {
    setCurrentPageSize(pageSize.toString());
  }, [pageSize]);

  // Generates an array of page numbers to display
  const displayedPages = useMemo(() => {
    const totalPages = pages.length;
    const maxDisplayedPages = 5;

    if (totalPages <= maxDisplayedPages) {
      return pages;
    }

    const left = Math.max(2, currentPage - 2);
    const right = Math.min(totalPages - 1, currentPage + 2);

    const newPages = [];

    newPages.push(1);

    if (left > 2) {
      newPages.push(-1); // Indicates an ellipsis
    }

    for (let i = left; i <= right; i++) {
      newPages.push(i);
    }

    if (right < totalPages - 1) {
      newPages.push(-1);
    }

    if (totalPages > 1) {
      newPages.push(totalPages);
    }

    return newPages;
  }, [pages, currentPage]);

  return (
    <div className="flex items-center justify-end gap-3">
      <span className="text-sm text-content-tertiary">
        {t('pagination.total', { total: total })}
      </span>

      <div className="ceramic-pill flex items-center gap-2 rounded-full p-1">
        <Pagination className="mx-0 w-auto">
          <PaginationContent className="gap-0.5">
            <PaginationItem>
              <PaginationPrevious
                onClick={handlePreviousPageChange}
                className={PagerRestClass}
              />
            </PaginationItem>

            {displayedPages.map((page, index) =>
              page === -1 ? (
                <PaginationItem key={`ellipsis-${index}`}>
                  <PaginationEllipsis className="text-content-tertiary" />
                </PaginationItem>
              ) : (
                <PaginationItem key={page}>
                  <PaginationLink
                    isActive={currentPage === page}
                    onClick={handlePageChange(page)}
                    className={
                      currentPage === page ? PagerCurrentClass : PagerRestClass
                    }
                  >
                    {page}
                  </PaginationLink>
                </PaginationItem>
              ),
            )}

            <PaginationItem>
              <PaginationNext
                onClick={handleNextPageChange}
                className={PagerRestClass}
              />
            </PaginationItem>
          </PaginationContent>
        </Pagination>

        {showSizeChanger && (
          <SelectWithSearch
            options={sizeChangerOptions}
            value={currentPageSize}
            onChange={handlePageSizeChange}
            triggerClassName="w-fit rounded-full border-cable-hairline bg-transparent"
          />
        )}
      </div>
    </div>
  );
}