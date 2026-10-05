import {
  SelectWithSearch,
  type SelectWithSearchFlagOptionType,
} from '@/components/originui/select-with-search';
import { DatasetIdentityMark } from '@/components/dataset-category';
import { useFetchKnowledgeBaseConfiguration } from '@/hooks/use-knowledge-request';
import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  StructureKinds,
  ViewMode,
  ViewModeLabelKeyMap,
  VisibleViewModes,
} from './constants';
import { DatasetStructureView } from './dataset-structure-view';
import { LlmWikiView } from './llm-wiki-view';
import { NavTreeView } from './nav-tree-view';
import { SkillsView } from './skills-view';

export default function Compilation() {
  const { t } = useTranslation();
  const { data: knowledgeBase } = useFetchKnowledgeBaseConfiguration();
  const [viewMode, setViewMode] = useState<ViewMode>(ViewMode.LlmWiki);

  const viewOptions = useMemo<SelectWithSearchFlagOptionType[]>(() => {
    return VisibleViewModes.map((mode) => ({
      value: mode,
      label: t(ViewModeLabelKeyMap[mode]),
    }));
  }, [t]);

  const handleViewModeChange = useCallback((value: string) => {
    setViewMode(value as ViewMode);
  }, []);

  const structureKind = StructureKinds.find((kind) => kind === viewMode);

  return (
    <section className="flex min-h-0 flex-col p-4 gap-3 h-full">
      <header className="shrink-0">
        <section className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* The knowledge base's card mark, so the third-level header names the
                same entity the same way the list and the sidebar do. Nothing is
                drawn until the record arrives, rather than a placeholder letter. */}
            {knowledgeBase && (
              <DatasetIdentityMark
                dataset={knowledgeBase}
                className="size-10"
                iconClassName="size-5"
              />
            )}
            <h2 className="text-xl font-medium text-text-primary">
              {knowledgeBase?.name}
              {t('knowledgeCompilation.compilationTitleSuffix')}
            </h2>
          </div>

          <SelectWithSearch
            options={viewOptions}
            value={viewMode}
            onChange={handleViewModeChange}
            triggerClassName="w-96"
          />
        </section>
      </header>

      {viewMode === ViewMode.LlmWiki && <LlmWikiView />}
      {viewMode === ViewMode.Skills && <SkillsView />}
      {viewMode === ViewMode.Tree && <NavTreeView />}
      {structureKind && <DatasetStructureView kind={structureKind} />}
    </section>
  );
}
