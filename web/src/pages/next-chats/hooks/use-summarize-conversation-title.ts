import { MessageType } from '@/constants/chat';
import { ChatApiAction } from '@/hooks/use-chat-request';
import chatService from '@/services/next-chat-service';
import api from '@/utils/api';
import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  useChatStreamMessages,
  useIsChatStreaming,
} from '../chat-stream/store';

/**
 * Conversations already summarised in this browser session. The summarizer costs
 * an LLM call, so a failed or finished attempt must not be retried on every
 * re-render (the effect below re-runs whenever the message list changes).
 */
const summarizedConversations = new Set<string>();

type SummarizeConversationTitleParams = {
  chatId?: string;
  sessionId?: string;
  /** Title currently shown, used to detect a user-renamed conversation. */
  currentTitle?: string;
  /** Model that should summarise; falls back to the tenant default. */
  llmId?: string;
  enabled?: boolean;
};

/**
 * Renames a conversation with an AI-summarised title once its first answer has
 * arrived. The title is only replaced while it is still a placeholder — the raw
 * first question, or the "new conversation" name a session created from the
 * dataset drawer carries until it has one — so a name the user typed by hand is
 * never overwritten.
 */
export const useSummarizeConversationTitle = ({
  chatId,
  sessionId,
  currentTitle,
  llmId,
  enabled = true,
}: SummarizeConversationTitleParams) => {
  const messages = useChatStreamMessages(sessionId ?? '');
  const isStreaming = useIsChatStreaming(sessionId ?? '');
  const queryClient = useQueryClient();
  const { t } = useTranslation();
  const [summarizing, setSummarizing] = useState(false);
  const inFlight = useRef(false);
  const placeholderTitle = t('chat.newConversation');

  const firstQuestion =
    messages.find((message) => message.role === MessageType.User)?.content ?? '';
  const hasAnswer = messages.some(
    (message) => message.role === MessageType.Assistant && message.content,
  );

  const renameConversation = useCallback(
    async (name: string) => {
      await chatService.updateSession(
        { url: api.updateSession(chatId as string, sessionId as string), data: { name } },
        true,
      );
      queryClient.invalidateQueries({
        queryKey: [ChatApiAction.FetchSessionList],
      });
    },
    [chatId, queryClient, sessionId],
  );

  useEffect(() => {
    if (
      !enabled ||
      !chatId ||
      !sessionId ||
      isStreaming ||
      !firstQuestion ||
      !hasAnswer ||
      inFlight.current ||
      summarizedConversations.has(sessionId)
    ) {
      return;
    }
    // The placeholder title the first message produced, or the one a session
    // created from the dataset drawer still carries, is the only title we may
    // replace; anything else means the user renamed the conversation.
    const title = currentTitle?.trim();
    if (title && title !== firstQuestion.trim() && title !== placeholderTitle) {
      return;
    }

    inFlight.current = true;
    setSummarizing(true);

    const summarize = async () => {
      try {
        const { data } = await chatService.chatTitle({
          chat_id: chatId,
          question: firstQuestion,
          llm_id: llmId,
        });
        const title = data?.data?.title;
        if (data?.code === 0 && title && title.trim() !== currentTitle?.trim()) {
          await renameConversation(title);
        }
      } catch {
        // Summarising is best effort: the raw first question stays as the title.
      } finally {
        summarizedConversations.add(sessionId);
        inFlight.current = false;
        setSummarizing(false);
      }
    };

    summarize();
  }, [
    chatId,
    currentTitle,
    enabled,
    firstQuestion,
    hasAnswer,
    isStreaming,
    llmId,
    placeholderTitle,
    renameConversation,
    sessionId,
  ]);

  return { summarizing };
};
