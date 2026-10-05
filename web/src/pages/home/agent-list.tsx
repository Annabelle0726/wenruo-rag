import { RenameDialog } from '@/components/rename-dialog';
import { useFetchAgentListByPage } from '@/hooks/use-agent-request';
import {
  AgentListItem,
  AgentListItemType,
  IFlow,
} from '@/interfaces/database/agent';
import { useEffect, useMemo } from 'react';
import { AgentCard } from '../agents/agent-card';
import { useRenameAgent } from '../agents/use-rename-agent';

export function Agents({
  setListLength,
  setLoading,
}: {
  setListLength: (length: number) => void;
  setLoading?: (loading: boolean) => void;
}) {
  const { data, loading } = useFetchAgentListByPage();
  const {
    agentRenameLoading,
    initialAgentName,
    onAgentRenameOk,
    agentRenameVisible,
    hideAgentRenameModal,
    showAgentRenameModal,
  } = useRenameAgent();

  const agentList = useMemo(
    () =>
      data.filter(
        (item): item is AgentListItem & { type: AgentListItemType.Agent } =>
          item.type !== AgentListItemType.CompilationTemplateGroup,
      ),
    [data],
  );

  useEffect(() => {
    setListLength(agentList?.length || 0);
    setLoading?.(loading || false);
  }, [agentList, setListLength, loading, setLoading]);

  return (
    <>
      {agentList.slice(0, 10).map((x) => (
        // The same card the agent list page renders: it carries the flow icon, the
        // saved/published dates and the tag row, so the preview and the page agree
        // on the card's height as well as its contents.
        <AgentCard
          key={x.id}
          data={x as unknown as IFlow & { type?: AgentListItemType }}
          showAgentRenameModal={showAgentRenameModal}
        />
      ))}
      {agentRenameVisible && (
        <RenameDialog
          hideModal={hideAgentRenameModal}
          onOk={onAgentRenameOk}
          initialName={initialAgentName}
          loading={agentRenameLoading}
        ></RenameDialog>
      )}
    </>
  );
}
