import { DataFlowSelect } from '@/components/data-pipeline-select';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import Divider from '@/components/ui/divider';
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
import { z } from 'zod';
import { ChunkMethodForm } from './chunk-method-form';
import ChunkMethodLearnMore from './chunk-method-learn-more';
import { ParseTypeItem } from '@/components/parse-type-form-field';
import { MainContainer } from './configuration-form-container';
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
    <div className="pr-5 pb-5">
      <Card className="p-0 h-full flex flex-col bg-transparent shadow-none">
        <CardHeader className="p-5 border-b-0.5 border-border-button">
          <header>
            <CardTitle as="h1">{t('knowledgeDetails.configuration')}</CardTitle>

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
                className="flex min-w-0 flex-1 flex-col"
              >
                <div className="flex-1 h-0 w-full max-w-[1200px] px-5 pt-5 overflow-y-auto scrollbar-auto">
                  <MainContainer className="text-text-secondary">
                    <div className="text-base font-medium text-text-primary">
                      {t('knowledgeConfiguration.baseInfo')}
                    </div>
                    <GeneralForm></GeneralForm>

                    <Divider />
                    <div className="text-base font-medium text-text-primary">
                      {t('knowledgeConfiguration.dataPipeline')}
                    </div>
                    <ParseTypeItem line={1} name="parse_type" />
                    {parseType === ParseType.BuiltIn && (
                      <>
                        <ChunkMethodItem
                          line={1}
                          name="chunk_method"
                        ></ChunkMethodItem>
                        {selectedTag && (
                          <ChunkMethodLearnMore parserId={selectedTag} />
                        )}
                      </>
                    )}
                    {parseType === ParseType.Pipeline && (
                      <DataFlowSelect
                        isMult={false}
                        showToDataPipeline={true}
                        formFieldName="pipeline_id"
                        layout={FormLayout.Horizontal}
                      />
                    )}

                    {parseType === ParseType.BuiltIn && <ChunkMethodForm />}
                  </MainContainer>
                </div>

                <div className="p-5 text-right items-center flex justify-end gap-3 w-full max-w-[1200px]">
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
