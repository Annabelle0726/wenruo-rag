import {
  AutoKeywordsFormField,
  AutoQuestionsFormField,
} from '@/components/auto-keywords-form-field';
import { ConfigurationFormContainer } from '../configuration-form-container';
import { AutoMetadata, GlobalIndexModelItem } from './common-item';
import { FormLayout } from '@/constants/form';
import { useTranslate } from '@/hooks/common-hooks';

export function AudioConfiguration() {
  const { t } = useTranslate('knowledgeConfiguration');
  return (
    <ConfigurationFormContainer
      title={t('intelligentEnrichment')}
      description={t('intelligentEnrichmentTip')}
    >
      <>
        <GlobalIndexModelItem />
        <AutoMetadata />
        <AutoKeywordsFormField
          layout={FormLayout.Horizontal}
        ></AutoKeywordsFormField>
        <AutoQuestionsFormField
          layout={FormLayout.Horizontal}
        ></AutoQuestionsFormField>
      </>

      {/* <TagItems></TagItems> */}
    </ConfigurationFormContainer>
  );
}
