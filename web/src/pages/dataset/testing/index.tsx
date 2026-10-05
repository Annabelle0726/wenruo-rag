import { useTestRetrieval } from '@/hooks/use-knowledge-request';
import { t } from 'i18next';
import TestingForm from './testing-form';
import { TestingResult } from './testing-result';

export default function RetrievalTesting() {
  const {
    loading,
    error,
    setValues,
    refetch,
    data,
    handleFilterSubmit,
    filterValue,
  } = useTestRetrieval();

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 pr-5 pb-5">
      <header className="flex shrink-0 flex-wrap items-baseline gap-x-4 gap-y-1 px-1 pt-1">
        <h1 className="text-2xl font-semibold tracking-tight text-text-primary">
          {t('knowledgeDetails.retrievalTesting')}
        </h1>
        <p className="text-sm text-text-secondary">
          {t('knowledgeDetails.retrievalTestingDescription')}
        </p>
      </header>

      <TestingForm
        loading={loading}
        setValues={setValues}
        refetch={refetch}
        result={
          <TestingResult
            data={data}
            loading={loading}
            error={error}
            filterValue={filterValue}
            handleFilterSubmit={handleFilterSubmit}
          />
        }
      />
    </div>
  );
}
