import { MessageType } from '@/constants/chat';
import { useTranslate } from '@/hooks/common-hooks';
import {
  ChatApiAction,
  useFetchChatList,
  useFetchSessionList,
  useGetChatSearchParams,
} from '@/hooks/use-chat-request';
import { IConversation } from '@/interfaces/database/chat';
import { generateTemporaryConversationId } from '@/utils/chat';
import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router';
import { useChatUrlParams } from './use-chat-url';

export const useFindPrologueFromDialogList = () => {
  const { id: dialogId } = useParams();
  const { data } = useFetchChatList();

  return data?.chats.find((x) => x.id === dialogId)?.prompt_config?.prologue;
};

/**
 * The placeholder row for a conversation the server does not know about yet.
 *
 * It is kept in the shared session-list cache rather than in the calling hook's
 * own state, because two views create and drop it: the rail raises the dataset
 * drawer for a new conversation, and the chat page falls back to a placeholder
 * when that drawer is dismissed. A copy held per caller would leave the rail
 * listing nothing while the page showed the placeholder, so the list every
 * consumer already renders from (`useFetchSessionList`'s cache) carries it.
 */
export const useTemporaryConversation = () => {
  const { t } = useTranslate('chat');
  const { id: dialogId } = useParams();
  const { setConversationBoth } = useChatUrlParams();
  const { setSearchString } = useFetchSessionList();
  const prologue = useFindPrologueFromDialogList();
  const queryClient = useQueryClient();

  const rewriteList = useCallback(
    (rewrite: (list: IConversation[]) => IConversation[]) => {
      if (!dialogId) return;
      queryClient.setQueryData<IConversation[]>(
        [ChatApiAction.FetchSessionList, dialogId],
        (previous) => rewrite(previous ?? []),
      );
    },
    [dialogId, queryClient],
  );

  const addTemporaryConversation = useCallback(() => {
    if (!dialogId) return;
    // Clear the search keyword, otherwise the newly created session will be
    // filtered out by the search after it is persisted and refetched.
    setSearchString('');
    // Open the placeholder conversation, so its prologue shows and the list
    // highlights the row. The id is marked temporary, which keeps every session
    // request away from the server until the first send creates the real one.
    //
    // Write the route BEFORE touching the list: writing it from inside a state
    // updater let React defer or re-run the update and left the previous
    // conversationId in the query string, so the page requested a session that
    // does not exist (`102 Session not found`).
    const conversationId = generateTemporaryConversationId();
    setConversationBoth(conversationId, 'true');

    const placeholder = {
      id: conversationId,
      name: t('newConversation'),
      chat_id: dialogId,
      is_new: true,
      messages: [
        {
          content: prologue ?? '',
          role: MessageType.Assistant,
        },
      ],
    } as IConversation;

    rewriteList((list) => [placeholder, ...list]);
  }, [dialogId, setConversationBoth, t, prologue, setSearchString, rewriteList]);

  const removeTemporaryConversation = useCallback(
    (conversationId: string) => {
      rewriteList((list) => list.filter((x) => x.id !== conversationId));
    },
    [rewriteList],
  );

  return {
    addTemporaryConversation,
    removeTemporaryConversation,
  };
};

export const useSelectDerivedConversationList = () => {
  const [list, setList] = useState<Array<IConversation>>([]);
  const {
    data: conversationList,
    loading,
    handleInputChange,
    searchString,
  } = useFetchSessionList();

  const { setConversationBoth } = useChatUrlParams();
  const { conversationId, isNew } = useGetChatSearchParams();

  useEffect(() => {
    setList([...conversationList]);
  }, [conversationList]);

  /**
   * Opening a chat without a conversation — a card click lands on `/chat/{id}`,
   * with no query string — used to leave the chat pane blank until the user
   * picked a row. Fall back to the first conversation of the list, which the
   * endpoint has already ordered by pin and activity, so the newest conversation
   * is what opens.
   *
   * A conversation already named in the URL is left alone, and so is a
   * placeholder the user just started: writing either of those would fight the
   * user's own choice, or reopen a placeholder under its temporary id.
   */
  useEffect(() => {
    if (conversationId || isNew === 'true') return;

    const firstConversation = conversationList[0];
    if (!firstConversation) return;

    setConversationBoth(firstConversation.id, '');
  }, [conversationId, isNew, conversationList, setConversationBoth]);

  return {
    list,
    loading,
    handleInputChange,
    searchString,
  };
};
