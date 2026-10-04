import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router';
import request from '@/utils/request';
import api from '@/utils/api';

interface Preparation {
  ready: boolean;
  can_write: boolean;
  can_manage_models: boolean;
  building: boolean;
  parsed_files: number;
  total_files: number;
  pipeline_id?: string;
  checks: Record<'parsed' | 'pipeline' | 'template' | 'models', boolean>;
  models: string[];
  stored_dimensions?: number[];
  compatibility: string;
}

export function useWikiPreparation() {
  const { id } = useParams();
  return useQuery<Preparation>({
    queryKey: ['wiki-preparation', id],
    enabled: !!id,
    refetchInterval: 5000,
    queryFn: async () => {
      const response = await request.get(`${api.artifactsList(id!)}/readiness`);
      if (response.data.code !== 0) throw new Error(response.data.message);
      return response.data.data;
    },
  });
}

export function WikiPreparation({
  data,
  failed,
}: {
  data?: Preparation;
  failed: boolean;
}) {
  const { t } = useTranslation();
  const { id } = useParams();
  const links = {
    parsed: `/dataset/files/${id}`,
    pipeline: data?.pipeline_id
      ? `/agent/${data.pipeline_id}`
      : `/dataset/configuration/${id}/parsing`,
    template: data?.pipeline_id ? `/agent/${data.pipeline_id}` : '/agents',
    models: '/user-setting/model',
  };
  return (
    <section
      className="mb-3 shrink-0 rounded-xl border border-border-button p-4 text-sm text-text-secondary"
      data-testid="wiki-preparation"
    >
      <p className="font-medium text-text-primary">
        {t('knowledgeCompilation.preparationTitle')}
      </p>
      <p className="mt-1">{t('knowledgeCompilation.preparationHelp')}</p>
      {!data ? (
        <p role="status">
          {t(
            failed
              ? 'knowledgeCompilation.preparationUnavailable'
              : 'knowledgeCompilation.preparationChecking',
          )}
        </p>
      ) : (
        <>
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
            {(Object.keys(links) as (keyof typeof links)[]).map((key) => (
              <span key={key}>
                {t(`knowledgeCompilation.preparation_${key}`)}:{' '}
                {t(
                  data.checks[key]
                    ? 'knowledgeCompilation.preparationReady'
                    : 'knowledgeCompilation.preparationMissing',
                )}
                {key === 'parsed' &&
                  ` (${data.parsed_files}/${data.total_files})`}
                {(key === 'models'
                  ? data.can_manage_models
                  : data.can_write) && (
                  <Link
                    className="ml-2 text-accent-primary underline"
                    to={links[key]}
                  >
                    {t('knowledgeCompilation.preparationConfigure')}
                  </Link>
                )}
              </span>
            ))}
          </div>
          <p className="mt-2">
            {t('knowledgeCompilation.preparationCompatibility')}{' '}
            {data.models.join(' / ')}
            {data.stored_dimensions?.length
              ? ` · ${data.stored_dimensions.join('/')}D`
              : ''}
          </p>
          <p>
            {t(
              data.can_write
                ? 'knowledgeCompilation.preparationSafety'
                : 'knowledgeCompilation.preparationReadOnly',
            )}
          </p>
          {data.building && (
            <p role="status">{t('knowledgeCompilation.preparationBuilding')}</p>
          )}
        </>
      )}
    </section>
  );
}
