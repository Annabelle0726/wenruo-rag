import { RenameDialog } from '@/components/rename-dialog';
import { useFetchChatList } from '@/hooks/use-chat-request';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { ChatCard } from '../next-chats/chat-card';
import { useRenameChat } from '../next-chats/hooks/use-rename-chat';

export function ChatList({
  setListLength,
  setLoading,
}: {
  setListLength: (length: number) => void;
  setLoading?: (loading: boolean) => void;
}) {
  const { t } = useTranslation();
  const { data, loading } = useFetchChatList();

  const {
    initialChatName,
    chatRenameVisible,
    showChatRenameModal,
    hideChatRenameModal,
    onChatRenameOk,
    chatRenameLoading,
  } = useRenameChat();
  useEffect(() => {
    setListLength(data?.chats?.length || 0);
    setLoading?.(loading || false);
  }, [data, setListLength, loading, setLoading]);
  return (
    <>
      {data?.chats.slice(0, 10).map((x) => (
        // The same card the chat list page renders, so a chat is the same size and
        // shows the same lines on the home page and on its own page.
        <ChatCard
          key={x.id}
          data={x}
          showChatRenameModal={showChatRenameModal}
        />
      ))}
      {chatRenameVisible && (
        <RenameDialog
          hideModal={hideChatRenameModal}
          onOk={onChatRenameOk}
          initialName={initialChatName}
          loading={chatRenameLoading}
          title={initialChatName || t('chat.createChat')}
        ></RenameDialog>
      )}
    </>
  );
}
