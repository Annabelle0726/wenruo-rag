import { useDatasetPreferences } from '@/hooks/use-dataset-preferences';
import { useKnowledgeBaseContext } from '../contexts/knowledge-base-context';

export function useDocumentVisibility() {
  const { knowledgeBase } = useKnowledgeBaseContext();
  const { isHidden } = useDatasetPreferences();
  const parentHidden = Boolean(knowledgeBase?.id && isHidden(knowledgeBase.id));
  return {
    parentHidden,
    isDocumentHidden: (status: string) => parentHidden || status === '0',
  };
}
