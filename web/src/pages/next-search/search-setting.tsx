/*
 *  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 */

// src/pages/next-search/search-setting.tsx

import AvatarNameDescription from '@/components/avatar-name-description';
import { Collapse } from '@/components/collapse';
import { KnowledgeBaseFormField } from '@/components/knowledge-base-item';
import { LlmSettingFieldItems } from '@/components/llm-setting-items/next';
import { MetadataFilter } from '@/components/metadata-filter';
import { RerankCandidatesCountFormField } from '@/components/rerank-candidates-count-item';
import { SettingsDrawer } from '@/components/settings-drawer';
import { SimilaritySliderFormField } from '@/components/similarity-slider';
import { Button } from '@/components/ui/button';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { MultiSelect } from '@/components/ui/multi-select';
import { Spin } from '@/components/ui/spin';
import { Switch } from '@/components/ui/switch';
import { useFetchKnowledgeMetadataKeys } from '@/hooks/use-knowledge-request';
import { useFetchDefaultModelDictionary } from '@/hooks/use-llm-request';
import {
  useRevalidateStaleDatasetIds,
  useStaleDatasetFormSchema,
} from '@/hooks/use-stale-dataset-validation';
import { useFetchTenantInfo } from '@/hooks/use-user-setting-request';
import { zodResolver } from '@hookform/resolvers/zod';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import {
  ISearchAppDetailProps,
  IUpdateSearchProps,
  IllmSettingProps,
  useUpdateSearch,
} from '../next-searches/hooks';
import { RerankFormFields } from '@/components/rerank';
import { resolveInitialLlmSetting } from './llm-setting-defaults';
import {
  SearchSettingFormData,
  useRevalidatePersistedModels,
  useSearchSettingFormSchema,
} from './search-setting-hooks';

/** The form lives in the drawer body; its footer button submits it by id. */
const SearchSettingsFormId = 'search-settings-form';

interface SearchSettingProps {
  open: boolean;
  setOpen: (open: boolean) => void;
  data: ISearchAppDetailProps;
}

function SearchSetting({ open = false, setOpen, data }: SearchSettingProps) {
  const { search_config } = data || {};
  const { llm_setting } = search_config || {};
  const { t } = useTranslation();
  const { formSchema: searchSettingSchema, modelsFetched } =
    useSearchSettingFormSchema();
  const { formSchema, datasetsFetched } = useStaleDatasetFormSchema(
    searchSettingSchema,
    search_config?.kb_ids,
    'search_config.kb_ids',
  );
  const formMethods = useForm<SearchSettingFormData>({
    resolver: zodResolver(formSchema),
    mode: 'onChange',
  });

  useRevalidateStaleDatasetIds(
    formMethods,
    datasetsFetched,
    'search_config.kb_ids',
  );
  const descriptionDefaultValue = t('search.descriptionValue');
  const resetForm = useCallback(() => {
    formMethods.reset({
      search_id: data?.id,
      name: data?.name || '',
      avatar: data?.avatar || '',
      description: data?.description || descriptionDefaultValue,
      search_config: {
        kb_ids: search_config?.kb_ids || [],
        // The fallbacks below are the platform defaults a new search app is
        // created with (api/db/cable_defaults.py). They only apply to a config
        // that never stored the parameter; a stored value is the operator's own.
        vector_similarity_weight:
          search_config?.vector_similarity_weight ?? 0.5,
        web_search: search_config?.web_search || false,
        doc_ids: [],
        similarity_threshold: search_config?.similarity_threshold ?? 0.55,
        use_kg: false,
        rerank_id: search_config?.rerank_id || '',
        use_rerank: search_config?.rerank_id ? true : false,
        rerank_candidates_count: search_config?.rerank_candidates_count ?? 30,
        summary: search_config?.summary || false,
        chat_id: search_config?.chat_id || '',
        llm_setting: {
          llm_id: search_config?.chat_id || '',
          parameter: llm_setting?.parameter || '',
          ...resolveInitialLlmSetting(llm_setting),
        },
        chat_settingcross_languages: [],
        highlight: false,
        keyword: false,
        related_search: search_config?.related_search || false,
        query_mindmap: search_config?.query_mindmap || false,
        meta_data_filter: search_config?.meta_data_filter,
        reference_metadata: {
          include: search_config?.reference_metadata?.include || false,
          fields:
            search_config?.reference_metadata?.fields &&
            search_config.reference_metadata.fields.length > 0
              ? search_config.reference_metadata.fields
              : undefined,
        },
      },
      temperatureEnabled: llm_setting?.temperature_enabled ?? true,
      topPEnabled: llm_setting?.top_p_enabled ?? true,
      presencePenaltyEnabled: llm_setting?.presence_penalty_enabled ?? true,
      frequencyPenaltyEnabled: llm_setting?.frequency_penalty_enabled ?? true,
    });
  }, [data, search_config, llm_setting, formMethods, descriptionDefaultValue]);

  useEffect(() => {
    resetForm();
  }, [resetForm]);

  // Cancelling drops the edits and closes the drawer; saving submits the form
  // from the drawer's footer and closes it once the update resolves.
  const handleCancel = useCallback(() => {
    resetForm();
    setOpen(false);
  }, [resetForm, setOpen]);

  const { rerankModelEnabled, aiSummaryEnabled } = useRevalidatePersistedModels(
    {
      control: formMethods.control,
      trigger: formMethods.trigger,
      modelsFetched,
    },
  );

  // Rerank is on by default for a search app, and the model it runs on is the
  // tenant's own default reranker — a switch with no model behind it is not a
  // default, it is an invalid form. The model list arrives after the form has
  // been reset, so the pair is filled in here once it does, and only while
  // neither field has been touched: an operator's own choice is never
  // overwritten, and a tenant with no reranker keeps the switch off rather than
  // being shown a required-model error it cannot satisfy.
  const { rerank_id: defaultRerankId } = useFetchDefaultModelDictionary();
  useEffect(() => {
    if (!defaultRerankId) return;
    if (formMethods.getValues('search_config.rerank_id')) return;
    if (
      formMethods.getFieldState('search_config.rerank_id').isDirty ||
      formMethods.getFieldState('search_config.use_rerank').isDirty
    ) {
      return;
    }

    formMethods.setValue('search_config.rerank_id', defaultRerankId);
    formMethods.setValue('search_config.use_rerank', true);
  }, [defaultRerankId, formMethods]);

  // The algorithm fields sit behind a disclosure, so an error on one of them
  // would block the save with nothing on screen to explain it — a persisted
  // rerank model that has since been deleted is the case that reaches here.
  // Any error under the fields the section owns opens it.
  const { errors } = formMethods.formState;
  const advancedFieldError = Boolean(
    errors.search_config?.similarity_threshold ||
    errors.search_config?.vector_similarity_weight ||
    errors.search_config?.rerank_candidates_count ||
    errors.search_config?.rerank_id,
  );

  const selectedKbIds = useWatch({
    control: formMethods.control,
    name: 'search_config.kb_ids',
  });
  const referenceMetadataEnabled = useWatch({
    control: formMethods.control,
    name: 'search_config.reference_metadata.include',
  });
  const { data: metadataKeys, loading: metadataKeysLoading } =
    useFetchKnowledgeMetadataKeys(selectedKbIds || []);
  const metadataFieldOptions = useMemo(() => {
    return (metadataKeys || []).map((key) => ({
      label: key,
      value: key,
    }));
  }, [metadataKeys]);

  useEffect(() => {
    const currentFields = formMethods.getValues(
      'search_config.reference_metadata.fields',
    );
    if (
      referenceMetadataEnabled &&
      Array.isArray(currentFields) &&
      currentFields.length > 0 &&
      metadataKeys
    ) {
      const validFields = currentFields.filter((field) =>
        metadataKeys.includes(field),
      );
      if (validFields.length !== currentFields.length) {
        formMethods.setValue(
          'search_config.reference_metadata.fields',
          validFields,
        );
      }
    } else if (!referenceMetadataEnabled) {
      formMethods.setValue(
        'search_config.reference_metadata.fields',
        undefined,
      );
    }
  }, [
    selectedKbIds,
    metadataKeys,
    metadataKeysLoading,
    referenceMetadataEnabled,
    formMethods,
  ]);

  const { updateSearch } = useUpdateSearch();
  const [formSubmitLoading, setFormSubmitLoading] = useState(false);
  const { data: systemSetting } = useFetchTenantInfo();
  const onSubmit = async (
    formData: IUpdateSearchProps & { tenant_id: string },
  ) => {
    try {
      setFormSubmitLoading(true);
      const {
        search_config,
        temperatureEnabled: _temperatureEnabled,
        topPEnabled: _topPEnabled,
        presencePenaltyEnabled: _presencePenaltyEnabled,
        frequencyPenaltyEnabled: _frequencyPenaltyEnabled,
        maxTokensEnabled: _maxTokensEnabled,
        ...other_formdata
      } = formData as IUpdateSearchProps & {
        tenant_id: string;
        temperatureEnabled?: boolean;
        topPEnabled?: boolean;
        presencePenaltyEnabled?: boolean;
        frequencyPenaltyEnabled?: boolean;
        maxTokensEnabled?: boolean;
      };
      void _maxTokensEnabled;
      const {
        llm_setting,
        vector_similarity_weight,
        use_rerank,
        rerank_id,
        ...other_config
      } = search_config;
      const llmSetting = {
        // llm_id: llm_setting.llm_id,
        parameter: llm_setting.parameter,
        temperature: llm_setting.temperature,
        top_p: llm_setting.top_p,
        frequency_penalty: llm_setting.frequency_penalty,
        presence_penalty: llm_setting.presence_penalty,
        temperature_enabled: _temperatureEnabled,
        top_p_enabled: _topPEnabled,
        frequency_penalty_enabled: _frequencyPenaltyEnabled,
        presence_penalty_enabled: _presencePenaltyEnabled,
      } as IllmSettingProps;
      const referenceMetadata = other_config.reference_metadata;
      const normalizedReferenceMetadata = referenceMetadata
        ? {
            ...referenceMetadata,
            ...(Array.isArray(referenceMetadata.fields) &&
            referenceMetadata.fields.length === 0
              ? { fields: undefined }
              : {}),
          }
        : referenceMetadata;

      await updateSearch({
        ...other_formdata,
        search_config: {
          ...other_config,
          reference_metadata: normalizedReferenceMetadata,
          chat_id: llm_setting.llm_id,
          vector_similarity_weight,
          rerank_id: use_rerank ? rerank_id : '',
          llm_setting: { ...llmSetting },
        },
        tenant_id: systemSetting.tenant_id,
      });
      setOpen(false);
    } catch (error) {
      console.error('Failed to update search:', error);
    } finally {
      setFormSubmitLoading(false);
    }
  };
  return (
    // The panel is the shared right-hand drawer, anchored to the search page so
    // its top edge lines up with the app bar's bottom edge and the search area
    // underneath keeps its full width while the drawer is closed.
    <SettingsDrawer
      open={open}
      onOpenChange={setOpen}
      title={t('search.searchSettings')}
      testId="search-settings-drawer"
      contained
      footer={
        <div className="flex items-center justify-end gap-3">
          <Button
            type="button"
            variant={'outline'}
            onClick={handleCancel}
            data-testid="search-settings-cancel"
          >
            {t('search.cancelText')}
          </Button>
          <Button
            data-testid="search-settings-save"
            type="submit"
            form={SearchSettingsFormId}
            disabled={formSubmitLoading}
          >
            {formSubmitLoading && (
              <div className="size-4">
                <Spin size="small" />
              </div>
            )}
            {t('search.okText')}
          </Button>
        </div>
      }
    >
      <div className="text-text-secondary">
        <Form {...formMethods}>
          <form
            id={SearchSettingsFormId}
            onSubmit={formMethods.handleSubmit(
              (data) => {
                onSubmit(data as unknown as IUpdateSearchProps);
              },
              (error) => {
                console.error(error, formMethods.getValues());
              },
            )}
            className="space-y-6"
          >
            <AvatarNameDescription avatarField="avatar" />

            <KnowledgeBaseFormField
              name="search_config.kb_ids"
              required
            ></KnowledgeBaseFormField>
            <MetadataFilter prefix="search_config."></MetadataFilter>
            <FormField
              control={formMethods.control}
              name="search_config.reference_metadata.include"
              render={({ field }) => (
                <FormItem className="flex flex-row items-start space-x-3 space-y-0">
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={(value) => {
                        field.onChange(value);
                        if (!value) {
                          formMethods.setValue(
                            'search_config.reference_metadata.fields',
                            undefined,
                          );
                        }
                      }}
                    />
                  </FormControl>
                  <FormLabel tooltip={t('chat.showChunkMetadataTip')}>
                    {t('chat.showChunkMetadata')}
                  </FormLabel>
                </FormItem>
              )}
            />
            {referenceMetadataEnabled && (
              <FormField
                control={formMethods.control}
                name="search_config.reference_metadata.fields"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel tooltip={t('chat.metadataFieldsTip')}>
                      {t('chat.metadataFields')}
                    </FormLabel>
                    <FormControl className="bg-bg-input">
                      <MultiSelect
                        options={metadataFieldOptions}
                        onValueChange={field.onChange}
                        showSelectAll={false}
                        placeholder={t('common.pleaseSelect')}
                        maxCount={20}
                        defaultValue={
                          Array.isArray(field.value) ? field.value : []
                        }
                        value={Array.isArray(field.value) ? field.value : []}
                        name={field.name}
                        ref={field.ref}
                        onBlur={field.onBlur}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}
            {/* The scoring parameters. An operator picks a knowledge base and
                asks a question; how the passages behind that answer are scored
                is not a decision they make, and the platform already ships a
                tuned default for every one of them. They stay behind this one
                disclosure, and they keep applying while it is closed. */}
            <div
              className="border-t border-cable-hairline pt-4"
              data-testid="search-settings-advanced"
            >
              <Collapse
                title={t('search.advancedSettings')}
                open={advancedFieldError || undefined}
              >
                <div className="space-y-6">
                  <SimilaritySliderFormField
                    isTooltipShown
                    similarityName="search_config.similarity_threshold"
                    similarityWeightName="search_config.vector_similarity_weight"
                    numberInputClassName="rounded-sm"
                  ></SimilaritySliderFormField>
                  <RerankCandidatesCountFormField name="search_config.rerank_candidates_count"></RerankCandidatesCountFormField>
                  {/* Rerank Model */}
                  <FormField
                    control={formMethods.control}
                    name="search_config.use_rerank"
                    render={({ field }) => (
                      <FormItem className="flex flex-row items-start space-x-3 space-y-0">
                        <FormControl>
                          <Switch
                            checked={field.value}
                            onCheckedChange={field.onChange}
                          />
                        </FormControl>
                        <FormLabel>{t('search.rerankModel')}</FormLabel>
                      </FormItem>
                    )}
                  />
                  {rerankModelEnabled && (
                    <>
                      <RerankFormFields
                        prefix={'search_config.'}
                        required
                      ></RerankFormFields>
                    </>
                  )}
                </div>
              </Collapse>
            </div>
            {/* AI Summary */}
            <FormField
              control={formMethods.control}
              name="search_config.summary"
              render={({ field }) => (
                <FormItem className="flex flex-row items-start space-x-3 space-y-0">
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={field.onChange}
                    />
                  </FormControl>
                  <FormLabel>{t('search.AISummary')}</FormLabel>
                </FormItem>
              )}
            />
            {aiSummaryEnabled && (
              <LlmSettingFieldItems
                prefix="search_config.llm_setting"
                llmRequired
                showFields={[
                  'temperature',
                  'top_p',
                  'presence_penalty',
                  'frequency_penalty',
                ]}
              ></LlmSettingFieldItems>
            )}
            {/* Feature Controls */}
            {/* <FormField
              control={formMethods.control}
              name="search_config.web_search"
              render={({ field }) => (
                <FormItem className="flex flex-row items-start space-x-3 space-y-0">
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={field.onChange}
                    />
                  </FormControl>
                  <FormLabel>{t('search.enableWebSearch')}</FormLabel>
                </FormItem>
              )}
            /> */}

            <FormField
              control={formMethods.control}
              name="search_config.related_search"
              render={({ field }) => (
                <FormItem className="flex flex-row items-start space-x-3 space-y-0">
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={field.onChange}
                    />
                  </FormControl>
                  <FormLabel>{t('search.enableRelatedSearch')}</FormLabel>
                </FormItem>
              )}
            />
            <FormField
              control={formMethods.control}
              name="search_config.query_mindmap"
              render={({ field }) => (
                <FormItem className="flex flex-row items-start space-x-3 space-y-0">
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={field.onChange}
                    />
                  </FormControl>
                  <FormLabel>{t('search.showQueryMindmap')}</FormLabel>
                </FormItem>
              )}
            />
          </form>
        </Form>
      </div>
    </SettingsDrawer>
  );
}

export { SearchSetting };
