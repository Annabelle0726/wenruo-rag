import { ChatSearchParams } from '@/constants/chat';
import { useGetChatSearchParams } from '@/hooks/use-chat-request';
import { IMessage } from '@/interfaces/database/chat';
import {
  isPersistedConversationId,
  isTemporaryConversationId,
} from '@/utils/chat';
import notification from '@/utils/notification';
import { useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router';
import { useChatStreamStore } from '../chat-stream/store';
import { useSetConversation } from './use-set-conversation';

/**
 * Consolidated hook for managing chat URL parameters (conversationId and isNew)
 * Replaces: useClickConversationCard from use-chat-request.ts and useSetChatRouteParams from use-set-chat-route.ts
 */
export const useChatUrlParams = () => {
  const [currentQueryParameters, setSearchParams] = useSearchParams();
  const newQueryParameters: URLSearchParams = useMemo(
    () => new URLSearchParams(currentQueryParameters.toString()),
    [currentQueryParameters],
  );

  const setConversationId = useCallback(
    (conversationId: string) => {
      newQueryParameters.set(ChatSearchParams.ConversationId, conversationId);
      setSearchParams(newQueryParameters);
    },
    [setSearchParams, newQueryParameters],
  );

  const setIsNew = useCallback(
    (isNew: string) => {
      newQueryParameters.set(ChatSearchParams.isNew, isNew);
      setSearchParams(newQueryParameters);
    },
    [setSearchParams, newQueryParameters],
  );

  const getIsNew = useCallback(() => {
    return newQueryParameters.get(ChatSearchParams.isNew);
  }, [newQueryParameters]);

  const setConversationBoth = useCallback(
    (conversationId: string, isNew: string) => {
      newQueryParameters.set(ChatSearchParams.ConversationId, conversationId);
      newQueryParameters.set(ChatSearchParams.isNew, isNew);
      setSearchParams(newQueryParameters);
    },
    [setSearchParams, newQueryParameters],
  );

  /**
   * Drops `conversationId` and `isNew` entirely, leaving a clean
   * `/chat/{dialogId}`. Used when the selected conversation is gone so the next
   * render starts a blank conversation instead of re-requesting a dead id.
   */
  const clearConversationParams = useCallback(() => {
    newQueryParameters.delete(ChatSearchParams.ConversationId);
    newQueryParameters.delete(ChatSearchParams.isNew);
    setSearchParams(newQueryParameters);
  }, [setSearchParams, newQueryParameters]);

  return {
    setConversationId,
    setIsNew,
    getIsNew,
    setConversationBoth,
    clearConversationParams,
  };
};

export function useCreateConversationBeforeSendMessage() {
  const { conversationId, isNew } = useGetChatSearchParams();
  const { setConversation } = useSetConversation();
  const { setConversationBoth } = useChatUrlParams();
  const removeStreamSessions = useChatStreamStore(
    (state) => state.removeSessions,
  );
  const { t } = useTranslation();

  /**
   * Makes sure the conversation the question belongs to exists on the server,
   * and returns the id the completion request must carry.
   *
   * Retrieval is scoped to a session row, so a conversation that only exists in
   * the browser (clicking "+") cannot answer: the request must be held back until
   * `POST /chats/{chat_id}/sessions` returns the real session id, which is then
   * written to the route and used for the stream. When creation fails the caller
   * gets `undefined` and must not send anything.
   */
  const createConversationBeforeSendMessage = useCallback(
    async (value: string) => {
      if (isPersistedConversationId(conversationId) && isNew !== 'true') {
        return {
          targetConversationId: conversationId,
          currentMessages: [] as Array<IMessage>,
        };
      }

      const data = await setConversation(value).catch(() => undefined);
      const backendConversationId =
        data?.code === 0 ? data?.data?.id ?? '' : '';

      if (!backendConversationId) {
        // Nothing was sent, so say why instead of dropping the question.
        notification.error({ message: t('chat.createSessionFailed') });
        return;
      }

      setConversationBoth(backendConversationId, '');

      // The placeholder is superseded by the persisted session.
      if (isTemporaryConversationId(conversationId)) {
        removeStreamSessions([conversationId]);
      }

      return {
        targetConversationId: backendConversationId,
        currentMessages: (data?.data?.messages ?? []) as Array<IMessage>,
      };
    },
    [
      conversationId,
      isNew,
      setConversation,
      setConversationBoth,
      removeStreamSessions,
      t,
    ],
  );

  return {
    createConversationBeforeSendMessage,
  };
}

export type CreateConversationBeforeSendMessageType = ReturnType<
  typeof useCreateConversationBeforeSendMessage
>['createConversationBeforeSendMessage'];

export type CreateConversationBeforeSendMessageReturnType = Awaited<
  ReturnType<CreateConversationBeforeSendMessageType>
>;
