import { ConfigurationFormContainer } from '../configuration-form-container';
import { GlobalIndexModelItem } from './common-item';
import { useTranslate } from '@/hooks/common-hooks';

export function ResumeConfiguration() {
  const { t } = useTranslate('knowledgeConfiguration');
  return (
    <ConfigurationFormContainer
      title={t('intelligentEnrichment')}
      description={t('intelligentEnrichmentTip')}
    >
      <GlobalIndexModelItem />
    </ConfigurationFormContainer>
  );
}
