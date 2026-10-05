import { DataFlowSelect } from '@/components/data-pipeline-select';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Form } from '@/components/ui/form';
import { DEFAULT_DATASET_LANGUAGE } from '@/constants/common';
import { FormLayout } from '@/constants/form';
import { DocumentParserType, ParseType } from '@/constants/knowledge';
import { PermissionRole } from '@/constants/permission';
import { IDataset } from '@/interfaces/database/dataset';
import { zodResolver } from '@hookform/resolvers/zod';
import { createContext, useEffect } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router';
import { z } from 'zod';
import { ChunkMethodForm } from './chunk-method-form';
import ChunkMethodLearnMore from './chunk-method-learn-more';
import { ParseTypeItem } from '@/components/parse-type-form-field';
import {
  ConfigurationFormContainer,
  MainContainer,
} from './configuration-form-container';
import { ChunkMethodItem } from './configuration/common-item';
import { formSchema } from './form-schema';
import { GeneralForm } from './general-form';
import { useFetchKnowledgeConfigurationOnMount } from './hooks';
import { SavingButton } from './saving-button';
const enum DocumentType {
  DeepDOC = 'DeepDOC',
  PlainText = 'Plain Text',
}
export const DataSetContext = createContext<{
  loading: boolean;
  knowledgeDetails: IDataset;
}>({ loading: false, knowledgeDetails: {} as IDataset });

export default function DatasetSettings() {
  const { t } = useTranslation();
  const { section = 'basic-info' } = useParams();

  const form = useForm<z.infer<typeof formSchema>>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      name: '',
      chunk_method: DocumentParserType.Naive,
      permission: PermissionRole.Me,
      department_ids: [],
      user_ids: [],
      language: DEFAULT_DATASET_LANGUAGE,
      parser_config: {
        layout_recognize: DocumentType.DeepDOC,
        chunk_token_num: 512,
        delimiter: `\n`,
        enable_children: false,
        children_delimiter: `\n`,
        auto_keywords: 0,
        auto_questions: 0,
        html4excel: false,
        topn_tags: 3,
        image_table_context_window: 0,
        overlapped_percent: 0,
        metadata: {
          type: 'object',
          properties: {},
          additionalProperties: false,
        },
        built_in_metadata: [],
        enable_metadata: false,
        llm_id: '',
      },
      pipeline_id: '',
      parse_type: ParseType.BuiltIn,
      pagerank: 0,
      connectors: [],
    },
  });
  const { knowledgeDetails, loading: datasetSettingLoading } =
    useFetchKnowledgeConfigurationOnMount(form);

  useEffect(() => {
    if (knowledgeDetails) {
      form.setValue(
        'parse_type',
        knowledgeDetails.pipeline_id ? ParseType.Pipeline : ParseType.BuiltIn,
      );
      form.setValue('pipeline_id', knowledgeDetails.pipeline_id || '');
    }
  }, [knowledgeDetails, form]);

  async function onSubmit(data: z.infer<typeof formSchema>) {
    try {
      console.log('Form validation passed, submit data', data);
    } catch (error) {
      console.error('An error occurred during submission:', error);
    }
  }

  const parseType = useWatch({
    control: form.control,
    name: 'parse_type',
    defaultValue: knowledgeDetails.pipeline_id
      ? ParseType.Pipeline
      : ParseType.BuiltIn,
  });
  const selectedTag = useWatch({
    name: 'chunk_method',
    control: form.control,
  });

  useEffect(() => {
    if (parseType === ParseType.BuiltIn) {
      form.setValue('pipeline_id', '');
    } else {
      form.setValue('chunk_method', DocumentParserType.Naive);
    }
  }, [parseType, form]);

  return (
    /* Normal flow, as this page has always laid out: the page is as tall as its
       sections, the shell's own region scrolls it, and the action row comes after the
       last section - where a reader who has finished the form finds it - instead of
       hovering over the fields. A definite page height would have pinned Save/Cancel
       and bought a second scroller inside the shell; the section cards below are what
       this restructure needed. */
    <div className="pr-5 pb-5">
      <Card className="p-0 h-full flex flex-col bg-transparent shadow-none">
        <CardHeader className="p-5 border-b-0.5 border-border-button">
          <header>
            {/* `CardTitle`/`CardDescription` are the app-wide card primitives
                (`src/components/ui/card.tsx`), so their own type is not this page's
                to change: the title takes the retrieval testing page's type through
                `className` instead (24px + 600 + -0.025em + primary ink, the same
                `text-2xl font-semibold tracking-tight text-text-primary` it uses;
                `leading-8` is that `text-2xl`'s own line-height, which the
                primitive's `leading-normal` would otherwise stretch). The
                subtitle primitive already IS `text-sm text-text-secondary`, i.e.
                the reference, and is left alone. */}
            <CardTitle
              as="h1"
              className="font-semibold leading-8 tracking-tight text-text-primary"
            >
              {t('knowledgeDetails.configuration')}
            </CardTitle>

            <CardDescription>
              {t('knowledgeConfiguration.titleDescription')}
            </CardDescription>

            {/* <Button>Save as Preset</Button> */}
          </header>
        </CardHeader>

        <CardContent className="p-0 flex-1 h-0 flex divide-x-0.5">
          <DataSetContext.Provider
            value={{
              loading: datasetSettingLoading,
              knowledgeDetails: knowledgeDetails,
            }}
          >
            <Form {...form}>
              <form
                onSubmit={form.handleSubmit(onSubmit)}
                className="flex w-full max-w-[1280px] min-w-0 flex-col"
              >
                <div className="flex-1 h-0 w-full max-w-[1280px] px-5 pt-5 overflow-y-auto scrollbar-auto">
                  <MainContainer className="text-text-secondary">
                    {section === 'parsing' ? (
                      <>
                        {/* Section 1: the mode itself. It is not part of the
                            parser's own fields - it decides which of the four
                            groups below even exist - so it is rendered here, on the
                            same surface as the rest. */}
                        <ConfigurationFormContainer
                          title={t('knowledgeConfiguration.parsingMode')}
                          description={t(
                            'knowledgeConfiguration.parsingModeTip',
                          )}
                        >
                          <ParseTypeItem line={1} name="parse_type" />
                          {parseType === ParseType.BuiltIn && (
                            <ChunkMethodItem line={1} name="chunk_method" />
                          )}
                          {parseType === ParseType.Pipeline && (
                            <>
                              <DataFlowSelect
                                isMult={false}
                                showToDataPipeline={true}
                                formFieldName="pipeline_id"
                                layout={FormLayout.Horizontal}
                              />
                              <div className="pl-[25%]">
                                <ChunkMethodLearnMore
                                  parserId={
                                    selectedTag || DocumentParserType.Naive
                                  }
                                />
                              </div>
                            </>
                          )}
                        </ConfigurationFormContainer>
                        {parseType === ParseType.BuiltIn && <ChunkMethodForm />}
                      </>
                    ) : (
                      <section className="space-y-5">
                        <header className="flex items-center gap-3">
                          <span className="h-6 w-1 rounded-full bg-accent-primary" />
                          <h2 className="text-lg font-semibold text-text-primary">
                            {t(
                              section === 'visibility'
                                ? 'knowledgeConfiguration.visibilitySettings'
                                : section === 'retrieval'
                                  ? 'knowledgeConfiguration.retrievalSettings'
                                  : 'knowledgeConfiguration.baseInfo',
                            )}
                          </h2>
                        </header>
                        <div className="rounded-xl border border-border-button bg-transparent p-6">
                          <GeneralForm section={section} />
                        </div>
                      </section>
                    )}
                  </MainContainer>
                </div>

                {/* The action row: in the document flow at the end of the form, with
                    a hairline above it and the page's own hierarchy - the filled Save
                    on the right, the quiet Cancel beside it. It is not fixed and not
                    sticky: it is the last row of the page, so nothing is pinned over
                    the fields and no scroller is added to keep it in view. */}
                <div className="flex items-center justify-end gap-3 w-full max-w-[1280px] border-t border-border-default px-5 py-4">
                  <Button
                    type="reset"
                    variant="transparent"
                    onClick={() => {
                      form.reset();
                    }}
                  >
                    {t('knowledgeConfiguration.cancel')}
                  </Button>

                  <SavingButton />
                </div>
              </form>
            </Form>
          </DataSetContext.Provider>
        </CardContent>
      </Card>
    </div>
  );
}
