import { useSetModalState } from '@/hooks/common-hooks';
import { useNavigatePage } from '@/hooks/logic-hooks/navigate-hooks';
import { useFetchAgentTemplates, useSetAgent } from '@/hooks/use-agent-request';

import { CardContainer } from '@/components/card-container';
import { AgentCategory } from '@/constants/agent';
import { IFlowTemplate } from '@/interfaces/database/agent';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { CreateAgentDialog } from './create-agent-dialog';
import {
  collectTemplateCategories,
  templateMatchesCategory,
} from './template-categories';
import { TemplateCard } from './template-card';
import { bindUnboundRetrieval } from './template-retrieval-binding';
import { MenuItemKey, SideBar } from './template-sidebar';

export default function AgentTemplates() {
  const list = useFetchAgentTemplates();
  const { loading, setAgent } = useSetAgent();
  const [templateList, setTemplateList] = useState<IFlowTemplate[]>([]);
  const [selectMenuItem, setSelectMenuItem] = useState<string>(
    MenuItemKey.Recommended,
  );

  useEffect(() => {
    setTemplateList(list);
  }, [list]);

  const {
    visible: creatingVisible,
    hideModal: hideCreatingModal,
    showModal: showCreatingModal,
  } = useSetModalState();

  const [template, setTemplate] = useState<IFlowTemplate>();

  const showModal = useCallback(
    (record: IFlowTemplate) => {
      setTemplate(record);
      showCreatingModal();
    },
    [showCreatingModal],
  );

  const { navigateToAgent } = useNavigatePage();

  const handleOk = useCallback(
    async (payload: any) => {
      const dsl = template?.dsl;
      const canvasCategory = template?.canvas_category;
      const datasetIds: string[] = payload?.dataset_ids ?? [];
      const memoryIds: string[] = payload?.memory_ids ?? [];
      const boundDsl =
        dsl && (datasetIds.length > 0 || memoryIds.length > 0)
          ? bindUnboundRetrieval(dsl, datasetIds, memoryIds)
          : dsl;

      const ret = await setAgent({
        title: payload.name,
        dsl: boundDsl,
        avatar: template?.avatar,
        canvas_category: canvasCategory,
      });

      if (ret?.code === 0) {
        hideCreatingModal();
        if (canvasCategory === AgentCategory.DataflowCanvas) {
          navigateToAgent(ret.data.id, AgentCategory.DataflowCanvas)();
        } else {
          navigateToAgent(ret.data.id)();
        }
      }
    },
    [
      hideCreatingModal,
      navigateToAgent,
      setAgent,
      template?.avatar,
      template?.canvas_category,
      template?.dsl,
    ],
  );
  const handleSiderBarChange = (keyword: string) => {
    setSelectMenuItem(keyword);
  };

  const tempListFilter = useMemo(() => {
    if (!selectMenuItem) {
      return templateList;
    }
    return templateList.filter((item) =>
      templateMatchesCategory(item, selectMenuItem),
    );
  }, [selectMenuItem, templateList]);

  const templateCategories = useMemo(
    () => collectTemplateCategories(templateList),
    [templateList],
  );

  return (
    <section className="flex size-full min-h-0 flex-1">
      {/* `h-dvh` here and on the grid below asked for a whole viewport inside a
          region that is already only `100dvh` minus the header and breadcrumb
          rows, and `max-h-[94vh]` capped the grid against the viewport instead of
          against the space it was actually in. The result was a grid whose bottom
          81px sat under the shell's `overflow-hidden`, so the last row of
          templates was clipped rather than scrollable. `size-full` + `min-h-0`
          makes the row fill the region it is given, and the grid scrolls inside
          that. */}
      <div className="flex size-full min-h-0 flex-1">
        <SideBar
          change={handleSiderBarChange}
          selected={selectMenuItem}
          categories={templateCategories}
        ></SideBar>

        <main className="flex min-h-0 flex-1 flex-col bg-text-title-invert/50">
          <CardContainer className="min-h-0 flex-1 overflow-auto px-8 pt-8 xl:grid-cols-4 2xl:grid-cols-5">
            {tempListFilter?.map((x) => {
              return (
                <TemplateCard
                  key={x.id}
                  data={x}
                  showModal={showModal}
                ></TemplateCard>
              );
            })}
          </CardContainer>
          {creatingVisible && (
            <CreateAgentDialog
              loading={loading}
              visible={creatingVisible}
              hideModal={hideCreatingModal}
              canvasCategory={template?.canvas_category as AgentCategory}
              template={template}
              onOk={handleOk}
            ></CreateAgentDialog>
          )}
        </main>
      </div>
    </section>
  );
}
