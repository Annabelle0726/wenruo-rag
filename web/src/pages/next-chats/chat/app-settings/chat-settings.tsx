import { SettingsDrawer } from '@/components/settings-drawer';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { DatasetMetadata } from '@/constants/chat';
import { useFetchChat, useUpdateChat } from '@/hooks/use-chat-request';
import { useFindLlmByUuid } from '@/hooks/use-llm-request';
import {
  useRevalidateStaleDatasetIds,
  useStaleDatasetFormSchema,
} from '@/hooks/use-stale-dataset-validation';
import {
  removeUselessFieldsFromValues,
  setLLMSettingEnabledValues,
} from '@/utils/form';
import { zodResolver } from '@hookform/resolvers/zod';
import { isEmpty, omit } from 'lodash';
import { useCallback, useEffect, useLayoutEffect, useRef } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router';
import { z } from 'zod';
import { getWebSearchProvider } from '../web-search-api-key';
import { ModelDatasetFields } from './sections/model-dataset-fields';
import { PrologueFields } from './sections/prologue-fields';
import { RetrievalFields } from './sections/retrieval-fields';
import { SystemPromptFields } from './sections/system-prompt-fields';
import { SavingButton } from './saving-button';
import { useChatSettingSchema } from './use-chat-setting-schema';
import { useRevealSubmitErrors } from './use-reveal-submit-errors';

type ChatSettingsProps = {
  /** Open state of the drawer. The chat page owns it so every trigger shares it. */
  visible: boolean;
  onVisibleChange: (visible: boolean) => void;
  /** Enters the multi-model comparison view from the model section. */
  onOpenMultiModel?: () => void;
  /**
   * The datasets the CHAT is bound to. They are the retrieval scope of every
   * conversation under it, so this is both what the dataset field edits and what
   * the notice above the accordion is about: a chat with datasets has nothing to
   * ask the user, whatever the open conversation is doing.
   */
  datasetIds?: string[];
};

/** The drawer's accordion sections. Which one comes up is decided on opening. */
const RetrievalSection = 'retrieval';
const SystemSection = 'system';
const PrologueSection = 'prologue';
const ModelSection = 'model';

const SettingsSections = [
  RetrievalSection,
  SystemSection,
  PrologueSection,
  ModelSection,
] as const;

const SettingsFormId = 'chat-settings-form';

export function ChatSettings({
  visible,
  onVisibleChange,
  onOpenMultiModel,
  datasetIds = [],
}: ChatSettingsProps) {
  const { data } = useFetchChat();

  const chatSettingSchema = useChatSettingSchema();
  // The ids the field opens on are the chat's own, which is also what this
  // lookup has to validate: a dataset the chat is bound to but can no longer
  // answer from is a staleness question, not an empty selection.
  const { formSchema, datasetsFetched } = useStaleDatasetFormSchema(
    chatSettingSchema,
    datasetIds,
  );
  const { updateChat, loading } = useUpdateChat();
  const findLlmByUuid = useFindLlmByUuid();
  const { id } = useParams();
  const { t } = useTranslation();

  const closeSettings = useCallback(() => {
    onVisibleChange(false);
  }, [onVisibleChange]);

  const {
    formContainerRef,
    handleInvalidSubmit,
    openSections,
    onOpenSectionsChange,
  } = useRevealSubmitErrors(SettingsSections);

  type FormSchemaType = z.infer<typeof formSchema>;

  const form = useForm<FormSchemaType>({
    resolver: zodResolver(formSchema),
    shouldUnregister: false,
    mode: 'onChange',
    defaultValues: {
      name: '',
      icon: '',
      description: '',
      dataset_ids: [],
      prompt_config: {
        quote: true,
        keyword: false,
        tts: false,
        refine_multiturn: true,
        system: '',
        parameters: [],
        reasoning: false,
        cross_languages: [],
        reference_metadata: {
          include: false,
          fields: undefined,
        },
      },
      top_n: 6,
      rerank_candidates_count: 64,
      similarity_threshold: 0.25,
      vector_similarity_weight: 0.3,
      meta_data_filter: {
        method: DatasetMetadata.Disabled,
        manual: [],
      },
    },
  });

  /**
   * Saves the drawer to the CHAT.
   *
   * This is the chat's settings panel and the chat owns the retrieval scope, so
   * the dataset field is part of the assistant payload like every other field
   * here: what it writes is the set every conversation under this chat answers
   * from. A conversation cannot be given a set of its own, which is what kept
   * one conversation quietly answering from another application's files.
   */
  async function onSubmit(values: FormSchemaType) {
    const nextValues: Record<string, any> = removeUselessFieldsFromValues(
      values,
      'llm_setting.',
    );
    const referenceMetadata =
      nextValues?.prompt_config?.reference_metadata;
    if (
      referenceMetadata &&
      Array.isArray(referenceMetadata.fields) &&
      referenceMetadata.fields.length === 0
    ) {
      referenceMetadata.fields = undefined;
    }

    // Add model_type to llm_setting based on the selected llm_id
    if (nextValues.llm_id) {
      nextValues.llm_setting = {
        ...nextValues.llm_setting,
        model_type: findLlmByUuid(nextValues.llm_id)?.model_type || 'chat',
      };
    }

    updateChat({
      chatId: id!,
      params: {
        ...omit(data, [
          'operator_permission',
          'tenant_id',
          'tenant_llm_id',
          'tenant_rerank_id',
          'created_by',
          'create_time',
          'create_date',
          'update_time',
          'update_date',
          'id',
          'top_k',
        ]),
        ...nextValues,
      },
    });
  }

  /**
   * The chat's own set as one value. The page rebuilds that array whenever the
   * assistant record is refetched, and re-seeding the form from an equal set
   * would throw away edits the user has not saved yet — so the seeding keys on
   * the contents rather than on the array.
   */
  const datasetIdsKey = datasetIds.join(',');

  useEffect(() => {
    const llmSettingEnabledValues = setLLMSettingEnabledValues(
      data?.llm_setting,
    );
    const referenceMetadata = data?.prompt_config?.reference_metadata;
    const normalizedReferenceMetadata =
      referenceMetadata &&
      Array.isArray(referenceMetadata.fields) &&
      referenceMetadata.fields.length === 0
        ? { ...referenceMetadata, fields: undefined }
        : referenceMetadata;

    const nextData = {
      ...omit(data, 'top_k'),
      // The field edits the chat, so it opens on the chat's own set — which is
      // also the set every conversation under it answers from.
      dataset_ids: datasetIdsKey ? datasetIdsKey.split(',') : [],
      prompt_config: {
        ...data?.prompt_config,
        // reset() skips undefined values, so fall back to '' to clear the field
        web_search_provider: getWebSearchProvider(data?.prompt_config) ?? '',
        reference_metadata: normalizedReferenceMetadata,
      },
      ...llmSettingEnabledValues,
    };

    if (!isEmpty(data)) {
      form.reset(nextData as FormSchemaType);
    }
  }, [data, form, datasetIdsKey]);

  useRevalidateStaleDatasetIds(form, datasetsFetched);

  /** The selection the drawer is showing. */
  const selectedDatasetIds = useWatch({
    control: form.control,
    name: 'dataset_ids',
  }) as string[] | undefined;

  /**
   * The one case the notice is about: the CHAT has no datasets at all, so a
   * conversation under it has nothing to answer from and the user has to choose.
   *
   * A chat that IS bound to datasets is never prompted about, whatever the open
   * conversation or the field currently holds: asking a user to pick what the
   * application already has is the 歧义提示 this rule exists to remove.
   */
  const hasNoDatasetSelected =
    isEmpty(selectedDatasetIds) && isEmpty(datasetIds);

  /**
   * The drawer reveals the model & dataset section — the one holding the field
   * the notice above the accordion is about — while the CHAT has no datasets,
   * and keeps the retrieval settings first otherwise.
   *
   * Decided on the opening edge, from the notice's own condition, never
   * re-applied while the panel is open: a selection made in the field must not
   * collapse the section the user is working in.
   */
  const showingNoticeRef = useRef(hasNoDatasetSelected);
  showingNoticeRef.current = hasNoDatasetSelected;

  useLayoutEffect(() => {
    if (!visible) return;

    onOpenSectionsChange(
      showingNoticeRef.current ? [ModelSection] : [RetrievalSection],
    );
  }, [visible, onOpenSectionsChange]);

  const sections = [
    {
      value: RetrievalSection,
      title: t('chat.retrievalSettings'),
      content: <RetrievalFields />,
    },
    {
      value: SystemSection,
      title: t('chat.roleAndPrompt'),
      content: <SystemPromptFields />,
    },
    {
      value: PrologueSection,
      title: t('chat.prologueAndFallback'),
      content: <PrologueFields />,
    },
    {
      value: ModelSection,
      title: t('chat.modelAndDataset'),
      content: <ModelDatasetFields onOpenMultiModel={onOpenMultiModel} />,
    },
  ];

  return (
    <SettingsDrawer
      open={visible}
      onOpenChange={onVisibleChange}
      title={t('chat.chatSetting')}
      testId="chat-detail-settings"
      footer={
        <div className="flex items-center justify-end gap-3">
          <Button
            variant={'outline'}
            onClick={closeSettings}
            data-testid="chat-detail-settings-cancel"
          >
            {t('chat.cancel')}
          </Button>
          <SavingButton
            loading={loading}
            form={SettingsFormId}
          ></SavingButton>
        </div>
      }
    >
      <Form {...form}>
        <form
          ref={formContainerRef}
          id={SettingsFormId}
          onSubmit={form.handleSubmit(onSubmit, handleInvalidSubmit)}
        >
          {/* The prompt a new conversation is opened with: nothing is selected,
              so there is nothing to retrieve an answer from until the field in
              the model & dataset section below is filled in. */}
          {hasNoDatasetSelected && (
            <p
              role="status"
              className="mb-4 rounded-xl border border-cable-border bg-cable-surface-muted p-3 text-sm text-text-secondary"
              data-testid="chat-settings-no-dataset"
            >
              {t('chat.datasetNotSelectedNotice')}
            </p>
          )}

          <Accordion
            type="multiple"
            value={openSections}
            onValueChange={onOpenSectionsChange}
            className="space-y-2"
          >
            {sections.map((section) => (
              <AccordionItem
                key={section.value}
                value={section.value}
                className="rounded-xl border border-cable-border px-4 data-[state=open]:bg-cable-surface-muted last:border-b last:border-cable-border"
              >
                <AccordionTrigger
                  className="text-sm font-medium text-text-primary hover:no-underline"
                  data-testid={`chat-settings-section-${section.value}`}
                >
                  {section.title}
                </AccordionTrigger>
                <AccordionContent>{section.content}</AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
          <div
            className="h-10 shrink-0 pointer-events-none"
            aria-hidden="true"
          />
        </form>
      </Form>
    </SettingsDrawer>
  );
}
