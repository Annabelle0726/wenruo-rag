import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
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
  model_details?: {
    role: string;
    reference?: string;
    source: string;
    model: string;
    provider: string;
    configured: boolean;
  }[];
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
  const [expanded, setExpanded] = useState(false);
  const links = {
    parsed: `/dataset/files/${id}`,
    pipeline: data?.pipeline_id
      ? `/agent/${data.pipeline_id}`
      : `/dataset/configuration/${id}/parsing`,
    template: data?.pipeline_id ? `/agent/${data.pipeline_id}` : '/agents',
    models: data?.pipeline_id
      ? `/agent/${data.pipeline_id}`
      : '/user-setting/model',
  };
  return (
    <section
      className="mb-3 shrink-0 rounded-xl border border-border-button px-4 py-3 text-sm text-text-secondary"
      data-testid="wiki-preparation"
    >
      <div className="flex items-center justify-between gap-3">
        <p className="font-medium text-text-primary">
          {t('knowledgeCompilation.preparationTitle')}
        </p>
        <button
          type="button"
          className="flex shrink-0 items-center gap-1 text-accent-primary hover:underline"
          aria-expanded={expanded}
          aria-controls="wiki-preparation-details"
          onClick={() => setExpanded((value) => !value)}
        >
          {t(
            expanded
              ? 'knowledgeCompilation.preparationCollapse'
              : 'knowledgeCompilation.preparationExpand',
          )}
          <ChevronDown
            className={`size-4 transition-transform ${expanded ? 'rotate-180' : ''}`}
          />
        </button>
      </div>
      <p className="mt-1">{t('knowledgeCompilation.preparationSummary')}</p>
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
          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {(Object.keys(links) as (keyof typeof links)[]).map((key) => (
              <span key={key} className="rounded-lg bg-bg-base px-3 py-2">
                {t(`knowledgeCompilation.preparation_${key}`)}:{' '}
                {t(
                  data.checks[key]
                    ? 'knowledgeCompilation.preparationReady'
                    : 'knowledgeCompilation.preparationMissing',
                )}
                {key === 'parsed' &&
                  ` (${data.parsed_files}/${data.total_files})`}
                {data.can_write && (
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
          {expanded && (
            <div
              id="wiki-preparation-details"
              className="mt-3 space-y-2 border-t border-border-button pt-3"
            >
              <p>{t('knowledgeCompilation.preparationHelp')}</p>
              <p>{t('knowledgeCompilation.preparationSafety')}</p>
              <p>
                {t('knowledgeCompilation.preparationCompatibility')}{' '}
                {!data.model_details?.length && data.models.join(' / ')}
                {data.stored_dimensions?.length
                  ? ` · ${data.stored_dimensions.join('/')}D`
                  : ''}
              </p>
              {data.model_details?.map((model, index) => (
                <p key={`${model.role}-${index}`}>
                  {model.role}:{' '}
                  {model.model || t('knowledgeCompilation.preparationMissing')}
                  {model.provider ? ` (${model.provider})` : ''} ·{' '}
                  {t(`knowledgeCompilation.modelSource_${model.source}`)} ·{' '}
                  {t(
                    model.configured
                      ? 'knowledgeCompilation.preparationReady'
                      : 'knowledgeCompilation.preparationMissing',
                  )}
                </p>
              ))}
              {data.can_manage_models && (
                <Link
                  className="text-accent-primary underline"
                  to="/user-setting/model"
                >
                  {t('knowledgeCompilation.adminModelSettings')}
                </Link>
              )}
            </div>
          )}
          <p className="mt-2">
            {t(
              data.can_write
                ? 'knowledgeCompilation.preparationSafetyBrief'
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
