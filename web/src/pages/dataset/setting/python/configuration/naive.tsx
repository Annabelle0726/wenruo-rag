import {
  AutoKeywordsFormField,
  AutoQuestionsFormField,
} from '@/components/auto-keywords-form-field';
import { ChildrenDelimiterForm } from '@/components/children-delimiter-form';
import { DelimiterFormField } from '@/components/delimiter-form-field';
import { ExcelToHtmlFormField } from '@/components/excel-to-html-form-field';
import { LayoutRecognizeFormField } from '@/components/layout-recognize-form-field';
import { MaxTokenNumberFormField } from '@/components/max-token-number-from-field';
import {
  ConfigurationFormContainer,
  MainContainer,
} from '../configuration-form-container';
import { useOwnerTenantId } from '../../../contexts/knowledge-base-context';
import {
  AutoMetadata,
  GlobalIndexModelItem,
  ImageContextWindow,
  OverlappedPercent,
  SLIDER_CONTROL_CLASS,
} from './common-item';
import { FormLayout } from '@/constants/form';
import { useTranslate } from '@/hooks/common-hooks';

/**
 * The 通用 (naive) parser, grouped the way the page is read.
 *
 * Through the parser page's grid, each of these four sections is its own surface:
 *
 *   解析模式              the mode and which parser it runs (rendered by the page)
 *   文档解析              how a document becomes text and where it is cut
 *   多模态与结构化内容      what happens to everything that is not plain prose
 *   智能增强              what is generated on top of the parsed text
 *
 * The fields, their order within a group, their names and their defaults are
 * unchanged; only the group each one is read in is now stated. `SLIDER_CONTROL_CLASS`
 * and the switch placements are the parser page's own presentation, asked for
 * explicitly so the parsing dialog keeps the layout it has always had.
 */
export function NaiveConfiguration() {
  const ownerTenantId = useOwnerTenantId();
  const { t } = useTranslate('knowledgeConfiguration');

  return (
    <MainContainer>
      <ConfigurationFormContainer
        title={t('documentParsing')}
        description={t('documentParsingTip')}
      >
        <LayoutRecognizeFormField
          testId="ds-settings-parser-pdf-parser-select"
          ownerTenantId={ownerTenantId}
          hintVariant="quiet"
        ></LayoutRecognizeFormField>
        <MaxTokenNumberFormField
          initialValue={512}
          controlClassName={SLIDER_CONTROL_CLASS}
          sliderTestId="ds-settings-parser-recommended-chunk-size-slider"
          numberInputTestId="ds-settings-parser-recommended-chunk-size-input"
        ></MaxTokenNumberFormField>
        <OverlappedPercent />
        <DelimiterFormField></DelimiterFormField>
      </ConfigurationFormContainer>

      <ConfigurationFormContainer
        title={t('multimodalContent')}
        description={t('multimodalContentTip')}
      >
        <ChildrenDelimiterForm switchPlacement="control" />
        <ImageContextWindow controlClassName={SLIDER_CONTROL_CLASS} />
        <ExcelToHtmlFormField switchPlacement="control"></ExcelToHtmlFormField>
      </ConfigurationFormContainer>

      <ConfigurationFormContainer
        title={t('intelligentEnrichment')}
        description={t('intelligentEnrichmentTip')}
      >
        <GlobalIndexModelItem />
        <AutoMetadata switchPlacement="control" />
        <AutoKeywordsFormField
          layout={FormLayout.Horizontal}
          controlClassName={SLIDER_CONTROL_CLASS}
        ></AutoKeywordsFormField>
        <AutoQuestionsFormField
          layout={FormLayout.Horizontal}
          controlClassName={SLIDER_CONTROL_CLASS}
        ></AutoQuestionsFormField>
      </ConfigurationFormContainer>
    </MainContainer>
  );
}
