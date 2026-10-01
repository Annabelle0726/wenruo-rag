import { DelimiterFormField } from '@/components/delimiter-form-field';
import { EntityTypesFormField } from '@/components/entity-types-form-field';
import { MaxTokenNumberFormField } from '@/components/max-token-number-from-field';
import {
  ConfigurationFormContainer,
  MainContainer,
} from '../configuration-form-container';
import { GlobalIndexModelItem, SLIDER_CONTROL_CLASS } from './common-item';
import { useTranslate } from '@/hooks/common-hooks';

/**
 * 知识图谱 parser: the entity types, the chunk size and the delimiter describe how a
 * document becomes text (文档解析); the index model is what is generated on top of it
 * (智能增强). The fields are unchanged - including the 16384-token limit this parser
 * asks for, which the shared field now simply renders in a bounded control.
 */
export function KnowledgeGraphConfiguration() {
  const { t } = useTranslate('knowledgeConfiguration');

  return (
    <MainContainer>
      <ConfigurationFormContainer
        title={t('documentParsing')}
        description={t('documentParsingTip')}
      >
        <EntityTypesFormField></EntityTypesFormField>
        <MaxTokenNumberFormField
          max={8192 * 2}
          controlClassName={SLIDER_CONTROL_CLASS}
        ></MaxTokenNumberFormField>
        <DelimiterFormField></DelimiterFormField>
      </ConfigurationFormContainer>

      <ConfigurationFormContainer
        title={t('intelligentEnrichment')}
        description={t('intelligentEnrichmentTip')}
      >
        <GlobalIndexModelItem />
      </ConfigurationFormContainer>
    </MainContainer>
  );
}
