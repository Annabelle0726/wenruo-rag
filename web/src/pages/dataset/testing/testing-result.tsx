import { EmptyType } from '@/components/empty/constant';
import Empty from '@/components/empty/empty';
import { FilterButton } from '@/components/list-filter-bar';
import { FilterPopover } from '@/components/list-filter-bar/filter-popover';
import { FilterCollection } from '@/components/list-filter-bar/interface';
import { Card } from '@/components/ui/card';
import { useTranslate } from '@/hooks/common-hooks';
import { useTestRetrieval } from '@/hooks/use-knowledge-request';
import { ITestingChunk } from '@/interfaces/database/dataset';
import { sanitizeHtmlWithImagesAsText } from '@/utils/dom-util';
import { t } from 'i18next';
import camelCase from 'lodash/camelCase';
import { CircleAlert, LoaderCircle } from 'lucide-react';
import { useMemo } from 'react';

const similarityList: Array<{ field: keyof ITestingChunk; label: string }> = [
  { field: 'similarity', label: 'Hybrid Similarity' },
  { field: 'term_similarity', label: 'Term Similarity' },
  { field: 'vector_similarity', label: 'Vector Similarity' },
];

const ChunkTitle = ({ item }: { item: ITestingChunk }) => {
  const { t } = useTranslate('knowledgeDetails');
  return (
    <div className="text-xs text-text-sub-title-invert italic space-x-4 rtl:space-x-reverse">
      {similarityList.map((x) => (
        <p key={x.field} className="inline">
          {((item[x.field] as number) * 100).toFixed(2)}{' '}
          <dfn>{t(camelCase(x.field))}</dfn>
        </p>
      ))}
    </div>
  );
};

type TestingResultProps = Pick<
  ReturnType<typeof useTestRetrieval>,
  'data' | 'filterValue' | 'handleFilterSubmit' | 'loading' | 'error'
>;

export function TestingResult({
  filterValue,
  handleFilterSubmit,
  loading,
  error,
  data,
}: TestingResultProps) {
  const filters: FilterCollection[] = useMemo(() => {
    return [
      {
        field: 'doc_ids',
        label: 'File',
        list:
          data.doc_aggs?.map((x) => ({
            id: x.doc_id,
            label: x.doc_name,
            count: x.count,
          })) ?? [],
      },
    ];
  }, [data.doc_aggs]);

  return (
    <article className="flex size-full min-h-0 flex-col">
      <header className="flex shrink-0 items-center justify-between border-b border-border-button px-5 py-3">
        <div className="flex items-baseline gap-2">
          <h2 className="text-base font-semibold leading-8 text-text-primary">
            {t('knowledgeDetails.testResults')}
          </h2>
          {data.isRuned && !loading && !error && (
            <span className="text-sm text-text-secondary">
              {t('common.total')}: {data.total}
            </span>
          )}
        </div>

        {data.isRuned && !error && (
          <FilterPopover
            filters={filters}
            onChange={handleFilterSubmit}
            value={filterValue}
          >
            <FilterButton />
          </FilterPopover>
        )}
      </header>

      {loading && (
        <div className="m-4 flex min-h-0 flex-1 items-center justify-center rounded-md border border-dashed border-border-button bg-bg-base p-5">
          <div className="flex flex-col items-center gap-3 text-sm font-medium text-text-secondary">
            <LoaderCircle className="size-6 animate-spin text-accent-primary" />
            {t('knowledgeDetails.retrievalLoading')}
          </div>
        </div>
      )}

      {!loading && error && (
        <div className="m-4 flex min-h-0 flex-1 items-center justify-center rounded-md border border-dashed border-border-button bg-bg-base p-5">
          <div className="max-w-sm text-center">
            <CircleAlert className="mx-auto mb-3 size-7 text-text-secondary" />
            <p className="text-sm font-medium text-text-primary">
              {t('knowledgeDetails.retrievalError')}
            </p>
            <p className="mt-1 break-words text-xs leading-5 text-text-secondary">
              {error.message}
            </p>
          </div>
        </div>
      )}

      {!loading && !error && data.chunks?.length > 0 && (
        <section className="flex min-h-0 flex-1 flex-col gap-5 overflow-auto px-5 pb-5 scrollbar-thin">
          {data.chunks.map((x) => (
            <article key={x.id}>
              <Card className="border border-border-button bg-bg-base px-5 py-3 shadow-none">
                <ChunkTitle item={x} />
                <div
                  className="!mt-2.5 whitespace-pre-wrap [&_em]:text-accent-primary [&_em]:not-italic"
                  dangerouslySetInnerHTML={{
                    __html: sanitizeHtmlWithImagesAsText(
                      x.highlight || x.content,
                    ),
                  }}
                />
                <div className="mt-2.5 text-right text-xs text-text-sub-title-invert">
                  {x.document_keyword}
                </div>
              </Card>
            </article>
          ))}
        </section>
      )}

      {!loading && !error && !data.chunks?.length && (
        <div className="m-4 flex min-h-0 flex-1 items-center justify-center rounded-md border border-dashed border-border-button bg-bg-base p-5">
          <Empty type={EmptyType.SearchData} iconWidth={72} className="gap-3">
            <div className="text-sm font-medium text-text-primary">
              {t(
                data.isRuned
                  ? 'knowledgeDetails.noTestResultsForRuned'
                  : 'knowledgeDetails.noTestResultsForNotRuned',
              )}
            </div>
          </Empty>
        </div>
      )}
    </article>
  );
}
