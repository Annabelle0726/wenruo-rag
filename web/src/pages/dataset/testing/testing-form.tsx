'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { useForm, useWatch } from 'react-hook-form';
import { z } from 'zod';

import { CrossLanguageFormField } from '@/components/cross-language-form-field';
import {
  RerankCandidatesCountFormField,
  rerankCandidatesCountSchema,
} from '@/components/rerank-candidates-count-item';
import {
  MetadataFilter,
  MetadataFilterSchema,
} from '@/components/metadata-filter';
import { RerankFormFields } from '@/components/rerank';
import {
  SimilaritySliderFormField,
  initialSimilarityThresholdValue,
  initialVectorSimilarityWeightValue,
  similarityThresholdSchema,
  vectorSimilarityWeightSchema,
} from '@/components/similarity-slider';
import { TopSelectFormItem } from '@/components/top-select';
import { ButtonLoading } from '@/components/ui/button';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormMessage,
} from '@/components/ui/form';
import { Textarea } from '@/components/ui/textarea';

import { useTestRetrieval } from '@/hooks/use-knowledge-request';
import { ITestRetrievalRequestBody } from '@/interfaces/request/knowledge';
import { trim } from 'lodash';
import { ChevronDown, Send } from 'lucide-react';
import { ReactNode, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router';
import { useOwnerTenantId } from '../contexts/knowledge-base-context';

type TestingFormProps = Pick<
  ReturnType<typeof useTestRetrieval>,
  'loading' | 'refetch' | 'setValues'
> & {
  result: ReactNode;
};

export default function TestingForm({
  loading,
  refetch,
  setValues,
  result,
}: TestingFormProps) {
  const { t } = useTranslation();
  const { id } = useParams();
  const ownerTenantId = useOwnerTenantId();
  const knowledgeBaseId = id;

  const formSchema = z
    .object({
      question: z.string().min(1, {
        message: t('knowledgeDetails.testTextPlaceholder'),
      }),
      ...similarityThresholdSchema,
      ...vectorSimilarityWeightSchema,
      dataset_ids: z.array(z.string()).optional(),
      ...MetadataFilterSchema,
      page_size: z.number().int().min(1).max(100),
      ...rerankCandidatesCountSchema,
    })
    .refine((values) => values.rerank_candidates_count >= values.page_size, {
      message: t('chat.rerankCandidatesCountValidation'),
      path: ['rerank_candidates_count'],
    });

  const form = useForm<z.infer<typeof formSchema>>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      ...initialSimilarityThresholdValue,
      ...initialVectorSimilarityWeightValue,
      dataset_ids: [knowledgeBaseId],
      page_size: 10,
      rerank_candidates_count: 64,
    },
  });

  const question = form.watch('question');

  const values = useWatch({ control: form.control });

  useEffect(() => {
    setValues(values as ITestRetrievalRequestBody);
  }, [setValues, values]);

  function onSubmit() {
    refetch();
  }

  return (
    <Form {...form}>
      <form
        className="flex min-h-0 flex-1 flex-col gap-4"
        onSubmit={form.handleSubmit(onSubmit)}
      >
        <section className="shrink-0 rounded-md border border-border-button bg-bg-card p-4">
          <FormField
            control={form.control}
            name="question"
            render={({ field }) => (
              <FormItem>
                <div className="mb-2 flex items-center justify-between gap-4">
                  <label className="text-sm font-semibold text-text-primary">
                    {t('knowledgeDetails.testQuestion')}
                  </label>
                  <span className="text-xs text-text-secondary">
                    {t('knowledgeDetails.testQuestionShortcut')}
                  </span>
                </div>
                <div className="relative">
                  <FormControl>
                    <Textarea
                      {...field}
                      className="min-h-24 resize-none bg-bg-card pb-12 pr-36"
                      placeholder={t('knowledgeDetails.testQuestionPlaceholder')}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault();
                          form.handleSubmit(onSubmit)();
                        }
                      }}
                    />
                  </FormControl>
                  <ButtonLoading
                    type="submit"
                    className="absolute bottom-3 right-3 h-9 shrink-0 px-4"
                    disabled={!trim(question)}
                    loading={loading}
                  >
                    {t('knowledgeDetails.testingLabel')}
                    <Send className="size-4" />
                  </ButtonLoading>
                </div>
                <FormMessage />
              </FormItem>
            )}
          />
        </section>

        <div className="grid min-h-0 flex-1 grid-cols-[minmax(19rem,22rem)_minmax(0,1fr)] gap-4">
          <article className="flex min-h-0 flex-col overflow-hidden rounded-md border border-border-button bg-bg-card">
            <header className="shrink-0 border-b border-border-button px-5 py-3">
              <h2 className="text-base font-semibold text-text-primary">
                {t('knowledgeDetails.retrievalParameters')}
              </h2>
            </header>
            <div className="min-h-0 flex-1 overflow-auto p-5">
              <div className="space-y-5">
                <SimilaritySliderFormField isTooltipShown={true} />
                <TopSelectFormItem />
                <details className="group rounded-md border border-border-button bg-bg-base p-3">
                  <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-medium text-text-primary">
                    <ChevronDown className="size-4 transition-transform group-open:rotate-180" />
                    {t('knowledgeDetails.advancedSettings')}
                  </summary>
                  <div className="mt-4 space-y-5 border-t border-border-button pt-4">
                    <RerankFormFields ownerTenantId={ownerTenantId} />
                    <CrossLanguageFormField name="cross_languages" />
                    <MetadataFilter prefix="" />
                    <RerankCandidatesCountFormField />
                    <p className="text-xs leading-5 text-text-secondary">
                      {t('knowledgeDetails.rerankCandidateValidationHint')}
                    </p>
                  </div>
                </details>
              </div>
            </div>
          </article>

          <div className="min-h-0 overflow-hidden rounded-md border border-border-button bg-bg-card">
            {result}
          </div>
        </div>
      </form>
    </Form>
  );
}
