import { CardIdentityIcon } from '@/components/card-identity-icon';
import { HomeCard } from '@/components/home-card';
import { MoreButton } from '@/components/more-button';
import { SharedBadge } from '@/components/shared-badge';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { AgentCategory } from '@/constants/agent';
import { useNavigatePage } from '@/hooks/logic-hooks/navigate-hooks';
import { AgentListItemType, IFlow } from '@/interfaces/database/agent';
import { CanvasCategoryToFlowType, FlowType, FlowTypeConfig } from './constant';
import { AgentDropdown } from './agent-dropdown';
import { useRenameAgent } from './use-rename-agent';
import { useTranslation } from 'react-i18next';
import { formatDate } from '@/utils/date';
import { Tag } from 'lucide-react';

export type DatasetCardProps = {
  data: IFlow & { type?: AgentListItemType };
} & Pick<ReturnType<typeof useRenameAgent>, 'showAgentRenameModal'>;

function AgentTypeIcon({
  data,
}: {
  data: IFlow & { type?: AgentListItemType };
}) {
  const { t } = useTranslation();
  const flowType =
    data.type === AgentListItemType.CompilationTemplateGroup
      ? FlowType.Compiler
      : CanvasCategoryToFlowType[data.canvas_category ?? ''];

  const config = flowType ? FlowTypeConfig[flowType] : null;

  if (!config) {
    return null;
  }

  const Icon = config.icon;

  return (
    <Button
      variant="ghost"
      size="sm"
      title={t(config.labelKey)}
      aria-label={t(config.labelKey)}
      className="pointer-events-none size-7 shrink-0 rounded-md border border-cable-hairline bg-cable-surface [&_svg]:size-4"
    >
      <Icon style={{ color: config.color }} />
    </Button>
  );
}

function AgentTags({ tags }: { tags?: string }) {
  const list = (tags || '')
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean);

  if (list.length === 0) return null;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="flex max-w-[42%] shrink-0 items-center gap-1 overflow-hidden">
          <Badge
            variant="secondary"
            className="h-5 max-w-28 truncate rounded-sm border border-cable-hairline bg-cable-surface px-1.5 text-[10px] font-medium leading-4 text-text-secondary"
          >
            <Tag className="mr-1 size-3 shrink-0" />
            <span className="truncate">{list[0]}</span>
          </Badge>
          {list.length > 1 && (
            <span className="shrink-0 rounded-sm border border-cable-hairline bg-cable-surface px-1 text-[10px] leading-4 tabular-nums text-text-secondary">
              +{list.length - 1}
            </span>
          )}
        </div>
      </TooltipTrigger>
      <TooltipContent>
        <div className="flex max-w-[280px] flex-wrap gap-1">
          {list.map((tag) => (
            <Badge
              key={tag}
              variant="secondary"
              className="space-x-1 text-xs font-normal"
            >
              <Tag className="size-3" />
              <span>{tag}</span>
            </Badge>
          ))}
        </div>
      </TooltipContent>
    </Tooltip>
  );
}

function AgentPublishStatus({ releaseTime }: { releaseTime?: number }) {
  const { t } = useTranslation();
  const isPublished = Boolean(releaseTime);
  const publishTime = releaseTime
    ? `${t('flow.publishedAt')}: ${formatDate(releaseTime, 'DD/MM/YYYY HH:mm')}`
    : undefined;

  return (
    <span
      title={publishTime}
      className={`inline-flex shrink-0 items-center gap-1 rounded-sm border px-1.5 text-[10px] font-medium leading-4 ${
        isPublished
          ? 'border-cable-brand/20 bg-cable-brand/10 text-cable-brand'
          : 'border-cable-hairline bg-cable-surface text-text-secondary'
      }`}
    >
      <span
        className={`size-1.5 rounded-full ${
          isPublished ? 'bg-cable-brand' : 'bg-cable-muted'
        }`}
        aria-hidden="true"
      />
      {t(isPublished ? 'flow.published' : 'flow.draft')}
    </span>
  );
}

export function AgentCard({ data, showAgentRenameModal }: DatasetCardProps) {
  const { navigateToAgent } = useNavigatePage();

  return (
    <HomeCard
      testId="agent-card"
      layout="agent"
      className="relative before:pointer-events-none before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-transparent before:content-[''] hover:before:bg-cable-brand"
      data={{
        ...data,
        name: data.title,
        description: data.description || '',
        release_time: data.release_time,
      }}
      // The agent's mark, from the same component the editor's header renders: an
      // uploaded avatar stays, and the bot glyph replaces the first-letter
      // placeholder the card used to fall back to.
      leading={<CardIdentityIcon kind="agent" avatar={data.avatar} />}
      moreDropdown={
        <AgentDropdown showAgentRenameModal={showAgentRenameModal} agent={data}>
          <MoreButton></MoreButton>
        </AgentDropdown>
      }
      sharedBadge={<SharedBadge>{data.nickname}</SharedBadge>}
      badge={<AgentPublishStatus releaseTime={data.release_time} />}
      onClick={
        // data.canvas_category === AgentCategory.DataflowCanvas
        //   ? navigateToDataflow(data.id)
        //   :
        navigateToAgent(data?.id, data.canvas_category as AgentCategory)
      }
      icon={<AgentTypeIcon data={data} />}
      extra={<AgentTags tags={data.tags} />}
    />
  );
}
