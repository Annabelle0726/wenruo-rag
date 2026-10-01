import { CardIdentityIcon } from '@/components/card-identity-icon';
import { HomeCard } from '@/components/home-card';
import { MoreButton } from '@/components/more-button';
import { useNavigatePage } from '@/hooks/logic-hooks/navigate-hooks';
import { IDialog } from '@/interfaces/database/chat';
import { ChatCardTrailing } from './chat-card-trailing';
import { ChatDropdown } from './chat-dropdown';
import { useRenameChat } from './hooks/use-rename-chat';

export type IProps = {
  data: IDialog;
} & Pick<ReturnType<typeof useRenameChat>, 'showChatRenameModal'>;

export function ChatCard({ data, showChatRenameModal }: IProps) {
  const { navigateToChat } = useNavigatePage();

  return (
    <HomeCard
      data={{
        name: data.name,
        description: data.description,
        update_time: data.update_time,
      }}
      leading={
        <CardIdentityIcon
          kind="chat"
          avatar={data.icon}
          className="rounded-md border border-cable-hairline"
        />
      }
      trailing={<ChatCardTrailing messageCount={data.message_count} />}
      layout="chat"
      className="relative bg-cable-surface shadow-[0_1px_2px_rgb(var(--text-primary)_/_0.06)] before:pointer-events-none before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-cable-hairline before:content-[''] hover:border-ceramic-border-hover hover:shadow-[0_2px_6px_rgb(var(--accent-primary)_/_0.12)] hover:before:bg-cable-brand"
      moreDropdown={
        <ChatDropdown chat={data} showChatRenameModal={showChatRenameModal}>
          <MoreButton></MoreButton>
        </ChatDropdown>
      }
      onClick={navigateToChat(data?.id)}
    />
  );
}
