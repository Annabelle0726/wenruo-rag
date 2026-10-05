import {
  useCreateSession,
  useGetChatSearchParams,
  useUpdateSession,
} from '@/hooks/use-chat-request';
import {
  isPersistedConversationId,
  isTemporaryConversationId,
} from '@/utils/chat';
import { trim } from 'lodash';
import { useCallback } from 'react';
import { useParams } from 'react-router';
import { useChatStreamStore } from '../chat-stream/store';
import { useChatUrlParams } from './use-chat-url';

type RenameSessionParams = {
  /** The session the user renamed; may still be a browser-only placeholder. */
  sessionId?: string;
  name: string;
};

/**
 * Renames a conversation, whether or not the server stores it yet.
 *
 * Clicking "+" only seeds a placeholder conversation in the browser, so it has no
 * row to PATCH: renaming it used to send the placeholder id to the session
 * endpoint, which answered "Session not found" and left the name unchanged.
 * Naming a placeholder creates the session instead, which both persists the name
 * and turns the placeholder into a real conversation the list can show.
 */
export const useRenameSession = () => {
  const { id: chatId } = useParams();
  const { conversationId: openConversationId } = useGetChatSearchParams();
  const { createSession, loading: creating } = useCreateSession();
  const { updateSession, loading: updating } = useUpdateSession();
  const { setConversationBoth } = useChatUrlParams();
  const removeStreamSessions = useChatStreamStore(
    (state) => state.removeSessions,
  );

  const renameSession = useCallback(
    async ({ sessionId, name }: RenameSessionParams) => {
      const trimmedName = trim(name);
      if (!chatId || trimmedName === '') {
        return false;
      }

      if (!isPersistedConversationId(sessionId)) {
        const data = await createSession({
          chatId,
          name: trimmedName,
        }).catch(() => undefined);

        const createdSessionId = data?.code === 0 ? data?.data?.id ?? '' : '';
        if (!createdSessionId) {
          return false;
        }

        // Follow the session that now exists only when the placeholder being
        // named is the open conversation: renaming another row in the list must
        // not navigate away from the conversation on screen.
        if (openConversationId === sessionId) {
          setConversationBoth(createdSessionId, '');
        }
        if (isTemporaryConversationId(sessionId)) {
          removeStreamSessions([sessionId]);
        }
        return true;
      }

      const data = await updateSession({
        chatId,
        sessionId,
        params: { name: trimmedName },
      }).catch(() => undefined);

      return data?.code === 0;
    },
    [
      chatId,
      openConversationId,
      createSession,
      updateSession,
      setConversationBoth,
      removeStreamSessions,
    ],
  );

  return { renameSession, loading: creating || updating };
};
