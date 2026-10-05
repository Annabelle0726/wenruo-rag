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

/**
 * 单个文档 (One) parser: the same two groups the 通用 parser shows, with the fields
 * this parser actually has - how a document becomes text, and what is generated on
 * top of it. The index model is read in the second group here as it is elsewhere.
 */
export function OneConfiguration() {
  const ownerTenantId = useOwnerTenantId();
  const { t } = useTranslate('knowledgeConfiguration');

  return (
    <MainContainer>
      <ConfigurationFormContainer
        title={t('documentParsing')}
        description={t('documentParsingTip')}
      >
        <LayoutRecognizeFormField
          ownerTenantId={ownerTenantId}
        ></LayoutRecognizeFormField>
        {/* <TagItems></TagItems> */}
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
    </MainContainer>
  );
}
