import { AvatarUpload } from '@/components/avatar-upload';
import { SelectWithSearch } from '@/components/originui/select-with-search';
import PageRankFormField from '@/components/page-rank-form-field';
import { RAGFlowFormItem } from '@/components/ragflow-form';
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import {
  DESCRIPTION_MAX_LENGTH,
  LanguageMap,
  LanguageTranslationMap,
} from '@/constants/common';
import { useMemo } from 'react';
import { useFormContext } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { useOwnerTenantId } from '../../contexts/knowledge-base-context';
import { EmbeddingModelItem } from './embedding-model-form-field';
import { PermissionFormField } from './permission-form-field';

export function GeneralForm({ section }: { section: string }) {
  const form = useFormContext();
  const { t } = useTranslation();
  const ownerTenantId = useOwnerTenantId();

  // Same two languages and the same stored values as the python variant; the labels
  // read in their own script. The default stays `DEFAULT_DATASET_LANGUAGE` ('Chinese').
  const languageOptions = useMemo(() => {
    return Object.keys(LanguageTranslationMap).map((x) => ({
      label: (LanguageMap as Record<string, string>)[x] ?? x,
      value: x,
    }));
  }, []);

  return (
    <>
      {section === 'basic-info' && (
        <div className="grid grid-cols-1 gap-x-8 gap-y-5 lg:grid-cols-2">
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem className="items-center space-y-0">
                <div className="flex">
                  <FormLabel className="text-sm whitespace-nowrap w-1/4">
                    <span className="text-red-600">*</span>
                    {t('common.name')}
                  </FormLabel>
                  <FormControl className="w-3/4">
                    <Input
                      {...field}
                      data-testid="ds-settings-basic-name-input"
                    ></Input>
                  </FormControl>
                </div>
                <div className="flex pt-1">
                  <div className="w-1/4"></div>
                  <FormMessage />
                </div>
              </FormItem>
            )}
          />
          <div className="items-center">
            <RAGFlowFormItem
              name="language"
              label={t('common.language')}
              horizontal={true}
            >
              <SelectWithSearch
                options={languageOptions}
                triggerClassName="w-full"
                testId="ds-settings-basic-language-select"
              ></SelectWithSearch>
            </RAGFlowFormItem>
          </div>
          <FormField
            control={form.control}
            name="avatar"
            render={({ field }) => (
              <FormItem className="items-center space-y-0">
                <div className="flex">
                  <FormLabel className="text-sm  whitespace-nowrap w-1/4">
                    {t('setting.avatar')}
                  </FormLabel>
                  <FormControl className="w-3/4">
                    <AvatarUpload
                      {...field}
                      uploadInputTestId="ds-settings-basic-avatar-upload"
                      cropModalTestId="ds-settings-basic-avatar-crop-modal"
                      cropModalOkButtonTestId="ds-settings-basic-avatar-crop-confirm-btn"
                    ></AvatarUpload>
                  </FormControl>
                </div>
                <div className="flex pt-1">
                  <div className="w-1/4"></div>
                  <FormMessage />
                </div>
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="description"
            render={({ field }) => {
              // null initialize empty string
              if (typeof field.value === 'object' && !field.value) {
                form.setValue('description', '');
              }
              return (
                <FormItem className="items-center space-y-0">
                  <div className="flex">
                    <FormLabel className="text-sm  whitespace-nowrap w-1/4">
                      {t('flow.description')}
                    </FormLabel>
                    <FormControl className="w-3/4">
                      <Input
                        {...field}
                        maxLength={DESCRIPTION_MAX_LENGTH}
                        placeholder={t(
                          'knowledgeConfiguration.datasetDescription',
                        )}
                        data-testid="ds-settings-basic-description-input"
                      ></Input>
                    </FormControl>
                  </div>
                  <div className="flex pt-1">
                    <div className="w-1/4"></div>
                    <FormMessage />
                  </div>
                </FormItem>
              );
            }}
          />
        </div>
      )}
      {section === 'visibility' && <PermissionFormField />}
      {section === 'retrieval' && (
        <div className="space-y-6">
          <EmbeddingModelItem
            isEdit={true}
            ownerTenantId={ownerTenantId}
          ></EmbeddingModelItem>
          <PageRankFormField></PageRankFormField>
        </div>
      )}
    </>
  );
}
