import { ConfirmDeleteDialog } from '@/components/confirm-delete-dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  useGetChatSearchParams,
  usePinSession,
  useRemoveSessions,
} from '@/hooks/use-chat-request';
import { IConversation } from '@/interfaces/database/chat';
import { Pin, PinOff, Trash2 } from 'lucide-react';
import { MouseEventHandler, PropsWithChildren, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useChatStreamStore } from '../chat-stream/store';
import { useChatUrlParams } from '../hooks/use-chat-url';

export function ConversationDropdown({
  children,
  conversation,
  removeTemporaryConversation,
}: PropsWithChildren & {
  conversation: IConversation;
  removeTemporaryConversation?: (conversationId: string) => void;
}) {
  const { t } = useTranslation();
  const { setConversationBoth } = useChatUrlParams();
  const { removeSessions } = useRemoveSessions();
  const { pinSession } = usePinSession();
  const { conversationId, isNew } = useGetChatSearchParams();
  const removeStreamSessions = useChatStreamStore(
    (state) => state.removeSessions,
  );

  const isPinned = !!conversation.is_pinned;

  // A placeholder conversation has no server row to pin, so the entry is not
  // offered until the first send has created the real session.
  const canPin = !conversation.is_new;

  const handleTogglePin = useCallback(() => {
    pinSession({ sessionId: conversation.id, isPinned: !isPinned });
  }, [conversation.id, isPinned, pinSession]);

  const handleDelete: MouseEventHandler<HTMLDivElement> =
    useCallback(async () => {
      if (isNew === 'true' && removeTemporaryConversation) {
        removeTemporaryConversation(conversation.id);
        removeStreamSessions([conversation.id]);
        if (conversationId === conversation.id) {
          setConversationBoth('', '');
        }
      } else {
        const code = await removeSessions([conversation.id]);
        if (code === 0) {
          removeStreamSessions([conversation.id]);
          setConversationBoth('', '');
        }
      }
    }, [
      conversation.id,
      conversationId,
      isNew,
      removeSessions,
      removeStreamSessions,
      removeTemporaryConversation,
      setConversationBoth,
    ]);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>{children}</DropdownMenuTrigger>
      <DropdownMenuContent>
        {canPin ? (
          <DropdownMenuItem
            // Radix reports both a pointer click and Enter/Space through
            // `onSelect`, and closes the menu afterwards, which is what a pin
            // should do; `preventDefault` is for the delete item below, whose
            // confirmation dialog needs the menu to stay put.
            onSelect={handleTogglePin}
            data-testid="chat-detail-session-pin"
            data-session-id={conversation.id}
          >
            {isPinned ? t('chat.unpin') : t('chat.pin')}
            {isPinned ? <PinOff /> : <Pin />}
          </DropdownMenuItem>
        ) : null}

        <ConfirmDeleteDialog onOk={handleDelete}>
          <DropdownMenuItem
            className="text-state-error"
            onSelect={(e) => {
              e.preventDefault();
            }}
            onClick={(e) => {
              e.stopPropagation();
            }}
            data-testid="chat-detail-session-delete"
            data-session-id={conversation.id}
          >
            {t('common.delete')} <Trash2 />
          </DropdownMenuItem>
        </ConfirmDeleteDialog>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
