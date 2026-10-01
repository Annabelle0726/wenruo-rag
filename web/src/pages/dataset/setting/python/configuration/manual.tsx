import {
  AutoKeywordsFormField,
  AutoQuestionsFormField,
} from '@/components/auto-keywords-form-field';
import { LayoutRecognizeFormField } from '@/components/layout-recognize-form-field';
import {
  ConfigurationFormContainer,
  MainContainer,
} from '../configuration-form-container';
import { useOwnerTenantId } from '../../../contexts/knowledge-base-context';
import { AutoMetadata, GlobalIndexModelItem } from './common-item';
import { FormLayout } from '@/constants/form';
import { useTranslate } from '@/hooks/common-hooks';

export function ManualConfiguration() {
  const { t } = useTranslate('knowledgeConfiguration');
  const ownerTenantId = useOwnerTenantId();
  return (
    <MainContainer>
      <ConfigurationFormContainer
        title={t('documentParsing')}
        description={t('documentParsingTip')}
      >
        <LayoutRecognizeFormField
          ownerTenantId={ownerTenantId}
        ></LayoutRecognizeFormField>
      </ConfigurationFormContainer>

      <ConfigurationFormContainer
        title={t('intelligentEnrichment')}
        description={t('intelligentEnrichmentTip')}
      >
        <GlobalIndexModelItem />
        <AutoMetadata />
        <AutoKeywordsFormField
          layout={FormLayout.Horizontal}
        ></AutoKeywordsFormField>
        <AutoQuestionsFormField
          layout={FormLayout.Horizontal}
        ></AutoQuestionsFormField>
      </ConfigurationFormContainer>

      {/* <TagItems></TagItems> */}
    </MainContainer>
  );
}
