import { Button } from '@/components/ui/button';
import {
  useFetchChat,
  useFetchSessionList,
  useFetchSessionManually,
  useGetChatSearchParams,
  usePatchChat,
} from '@/hooks/use-chat-request';
import { useFetchDatasetsByIds } from '@/hooks/use-knowledge-request';
import { useSetModalState } from '@/hooks/common-hooks';
import { IClientConversation } from '@/interfaces/database/chat';
import { BreadcrumbTrail } from '@/layouts/components/breadcrumb-context';
import type { BreadcrumbCrumb } from '@/layouts/components/breadcrumb-context';
import { RootLayoutContainer } from '@/layouts/root-layout';
import { cn } from '@/lib/utils';
import { Routes } from '@/routes';
import { isPersistedConversationId } from '@/utils/chat';
import { isEmpty } from 'lodash';
import { LucideArrowBigLeft } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router';
import { useHandleClickConversationCard } from '../hooks/use-click-card';
import { useChatUrlParams } from '../hooks/use-chat-url';
import { useTemporaryConversation } from '../hooks/use-select-conversation-list';
import { useSummarizeConversationTitle } from '../hooks/use-summarize-conversation-title';
import { ChatSettings } from './app-settings/chat-settings';
import { MultipleChatBox } from './chat-box/next-multiple-chat-box';
import { SingleChatBox } from './chat-box/single-chat-box';
import { ConversationHeader } from './conversation-header';
import { resolveDatasetTags } from './dataset-tags';
import { Sessions } from './sessions';
import { useAddChatBox } from './use-add-box';
import { useSwitchDebugMode } from './use-switch-debug-mode';

export default function Chat() {
  const { t } = useTranslation();
  const [currentConversation, setCurrentConversation] =
    useState<IClientConversation>({} as IClientConversation);

  const { fetchSessionManually } = useFetchSessionManually();

  const { handleConversationCardClick, controller, stopOutputMessage } =
    useHandleClickConversationCard();

  const { isDebugMode, switchDebugMode } = useSwitchDebugMode();
  const { removeChatBox, addChatBox, chatBoxIds, hasSingleChatBox } =
    useAddChatBox(isDebugMode);

  const { conversationId } = useGetChatSearchParams();
  const { id: chatId } = useParams();
  const { clearConversationParams } = useChatUrlParams();

  const { data: dialogList } = useFetchSessionList();
  const { data: currentDialog, loading: chatLoading } = useFetchChat();
  const { patchChat } = usePatchChat();

  // Lifted out of `Sessions` so the header can mirror it: while the conversation
  // list is open the header drops its title (the list already highlights the
  // active conversation), and it reappears once the list is collapsed.
  const [sessionsVisible, setSessionsVisible] = useState(true);

  const handleExpandSessions = useCallback(() => {
    setSessionsVisible(true);
  }, []);

  /**
   * The header's model dropdown writes straight to the chat record with a
   * partial PATCH — it resolves the paired tenant model id server-side and
   * leaves every other field alone. The settings drawer reads the same record,
   * so it opens on the new model.
   */
  const handleModelChange = useCallback(
    (nextLlmId: string) => {
      if (!chatId || !nextLlmId || nextLlmId === currentDialog?.llm_id) {
        return;
      }
      patchChat({ chatId, params: { llm_id: nextLlmId } });
    },
    [chatId, currentDialog?.llm_id, patchChat],
  );

  /**
   * The one settings drawer, with three triggers: the gear at the top of the
   * conversation list, the gear in the chat header that replaces it while the
   * list is collapsed, and the dataset tags — which is where a conversation's
   * datasets are changed, because the dataset field lives in this panel.
   *
   * It also raises itself once for a conversation with nothing selected to
   * retrieve from; see the effect below.
   */
  const {
    visible: settingsVisible,
    showModal: showSettings,
    hideModal: hideSettings,
  } = useSetModalState();

  const { addTemporaryConversation } = useTemporaryConversation();

  /**
   * The datasets the CHAT is bound to. They are the retrieval scope of every
   * conversation under it: a conversation has no set of its own, so this is what
   * the settings drawer edits, what its notice is about, what the header tags
   * name, and what a turn answers from.
   */
  const chatDatasetIds = useMemo(
    () => currentDialog?.dataset_ids ?? [],
    [currentDialog?.dataset_ids],
  );

  /**
   * Names for those ids, resolved here rather than in the header's tag row: the
   * row is a leaf of a presentational header that its own suite renders without
   * the app shell, so the dataset request (and the router behind it) must not be
   * reachable from it.
   */
  const { data: chatDatasets } = useFetchDatasetsByIds(chatDatasetIds);

  const datasetTags = useMemo(
    () => resolveDatasetTags(chatDatasetIds, chatDatasets),
    [chatDatasetIds, chatDatasets],
  );

  /**
   * The rail's "+": a conversation the browser only holds a placeholder for.
   * It answers from the chat's datasets like every other conversation — which is
   * why it needs no dataset of its own, and why nothing has to be chosen before
   * the first question unless the chat itself has none.
   */
  const handleStartNewConversation = useCallback(() => {
    addTemporaryConversation();
  }, [addTemporaryConversation]);

  /**
   * Every entry point into the conversation's datasets opens this one panel:
   * the gear in the conversation list, the gear in the chat header, and the
   * dataset tags. There is no second picker.
   */
  const handleOpenSettings = useCallback(() => {
    showSettings();
  }, [showSettings]);

  // The multi-model comparison view is entered from the settings drawer's model
  // section, not from the header, which keeps that row to one line.
  const handleOpenMultiModel = useCallback(() => {
    hideSettings();
    switchDebugMode();
  }, [hideSettings, switchDebugMode]);

  const currentConversationName = useMemo(() => {
    return (
      dialogList.find((x) => x.id === conversationId)?.name ||
      t('chat.newConversation')
    );
  }, [conversationId, dialogList, t]);

  /**
   * Titling lives here, on the page, rather than in the header that displays it.
   *
   * The header is mounted only while the conversation list is collapsed, and the
   * list is open by default — so while the titler was inside it, a question asked
   * with the list open was never summarised at all and the conversation kept its
   * raw first question as the title, which is exactly what the list is meant to
   * show a summary of. The page is mounted for the whole visit.
   */
  const { summarizing } = useSummarizeConversationTitle({
    chatId,
    sessionId: conversationId,
    currentTitle: currentConversationName,
    llmId: currentDialog?.llm_id,
    enabled: isPersistedConversationId(conversationId),
  });

  /**
   * 聊天 > 助手 > 会话.
   *
   * The level naming the assistant keeps a link back to `/chat/:id` with no
   * `conversationId`, which is what drops the open session and lands on the
   * assistant's main view. The session level only appears once the server has a
   * named conversation for the id in the URL: a placeholder id, or a list that has
   * not arrived yet, would otherwise put a "新会话" placeholder in the trail.
   */
  const breadcrumbTrail = useMemo(() => {
    if (!chatId) {
      return [];
    }

    const crumbs: BreadcrumbCrumb[] = [
      {
        label: currentDialog?.name || t('breadcrumb.newChat'),
        to: `${Routes.Chat}/${chatId}`,
      },
    ];
    const sessionName = dialogList.find((x) => x.id === conversationId)?.name;

    if (isPersistedConversationId(conversationId) && sessionName) {
      crumbs.push({ label: sessionName });
    }

    return crumbs;
  }, [chatId, conversationId, currentDialog?.name, dialogList, t]);

  /**
   * How each conversation's load ended: `ready` once its messages are in hand,
   * `failed` when the attempt produced none. Absent means "never attempted", which
   * is what the loading state reads as — so the render that follows a click shows
   * the loading screen without an effect having to set a flag first.
   *
   * Both terminal states are recorded, not just success: a spinner that only stops
   * on success is a spinner that never stops when the request is rejected or the
   * session is gone, and the row it belongs to is disabled while it waits.
   */
  const [sessionLoadState, setSessionLoadState] = useState<
    Record<string, 'ready' | 'failed'>
  >({});

  /**
   * Ids this mount has already attempted. A session's messages arrive into the
   * stream store keyed by id, so re-requesting one the pane already holds is pure
   * duplication — and this effect re-runs whenever the query string changes (the
   * `isNew` flag, the placeholder-to-real id swap after the first send), which is
   * most of the duplicate fetches. A failed attempt releases the id so a later
   * click can try again.
   */
  const attemptedConversationIds = useRef(new Set<string>());

  /**
   * Bumped when a row whose last attempt failed is picked again. Re-selecting the
   * same session leaves the URL unchanged, so nothing would re-run the load below;
   * the token is what turns that click into a retry.
   */
  const [retryToken, setRetryToken] = useState(0);

  const loadState = sessionLoadState[conversationId];

  const isLoadingMessages =
    isPersistedConversationId(conversationId) &&
    loadState !== 'ready' &&
    loadState !== 'failed';

  /**
   * Chats whose empty dataset set has already raised the settings drawer, so the
   * rule below fires at most ONCE for a chat in a visit.
   *
   * Keyed by the CHAT and not by the conversation, because the chat is what has
   * no datasets: a chat with none would otherwise raise the panel again on every
   * conversation opened under it — the first question of each one is not a new
   * question for the user, and the panel has already said what it has to say.
   */
  const autoRaisedSettingsFor = useRef(new Set<string>());

  /**
   * The one rule behind the drawer raising itself: a chat with NO datasets opens
   * the settings drawer, marked by the notice inside it, so the selection is
   * guided before the first question. That is the only case there is — a chat
   * bound to datasets is never prompted about, because every conversation under
   * it answers from them already, and a conversation that inherits a non-empty
   * set is therefore never "missing" anything.
   *
   * It fires once per chat (the record above), which is what also stops it from
   * looping and from reopening the panel over the user's own close: by the time
   * they dismiss it the chat is already recorded. It waits only for the read it
   * derives the condition from — the chat itself — and for no answer to be
   * mid-load, so a set still in flight is never read as empty and the panel
   * never lands over a transcript being fetched.
   */
  useEffect(() => {
    if (!chatId || chatLoading || isLoadingMessages) return;
    if (chatDatasetIds.length > 0) return;
    if (autoRaisedSettingsFor.current.has(chatId)) return;

    autoRaisedSettingsFor.current.add(chatId);
    showSettings();
  }, [
    chatId,
    chatLoading,
    isLoadingMessages,
    chatDatasetIds.length,
    showSettings,
  ]);

  const handleSessionClick = useCallback(
    (id: string, isNew: boolean) => {
      if (sessionLoadState[id] === 'failed') {
        attemptedConversationIds.current.delete(id);
        setSessionLoadState((previous) => {
          const next = { ...previous };
          delete next[id];
          return next;
        });
        setRetryToken((token) => token + 1);
      }

      handleConversationCardClick(id, isNew);
    },
    [handleConversationCardClick, sessionLoadState],
  );

  // The URL is the single source of truth for which conversation is open:
  // card clicks, "+" and the temp→real id swap after the first send all land
  // here. Clear first so the previous conversation's messages and references
  // can never leak into the newly opened one while the fetch is in flight.
  useEffect(() => {
    setCurrentConversation((previous) =>
      isEmpty(previous) ? previous : ({} as IClientConversation),
    );
    // A placeholder conversation has no server row to fetch, so only a persisted
    // id is worth a request — the placeholder's messages come from the prologue
    // seeded in the stream store.
    if (!isPersistedConversationId(conversationId)) return;
    if (attemptedConversationIds.current.has(conversationId)) return;

    attemptedConversationIds.current.add(conversationId);
    const settle = (state: 'ready' | 'failed') => {
      setSessionLoadState((previous) =>
        previous[conversationId] === state
          ? previous
          : { ...previous, [conversationId]: state },
      );
    };

    fetchSessionManually(conversationId)
      .then((conversation) => {
        if (!conversation) {
          // The session is gone (deleted elsewhere, stale link, or a temp id that
          // never reached the server). Record the failure so the row stops waiting
          // and drops the dead id so this page settles into a blank conversation
          // instead of showing an empty shell; the request itself already
          // suppressed the "102 Session not found" toast.
          attemptedConversationIds.current.delete(conversationId);
          settle('failed');
          clearConversationParams();
          return;
        }

        // Written even if the operator has since moved on: the result belongs to
        // this id, the transcript ignores a conversation that is not the open one,
        // and holding it here is what makes returning to the session instant.
        setCurrentConversation(conversation);
        settle('ready');
      })
      .catch(() => {
        // A transport failure is not a dead session: release the id so the row can
        // be clicked again, and stop its spinner.
        attemptedConversationIds.current.delete(conversationId);
        settle('failed');
      });
  }, [
    conversationId,
    fetchSessionManually,
    clearConversationParams,
    retryToken,
  ]);

  if (isDebugMode) {
    return (
      <section
        className="pt-5 pb-14 h-[100vh] flex flex-col"
        data-testid="chat-detail-multimodel-root"
      >
        <header className="px-10 pb-5">
          <div className="mb-5">
            <Button
              variant="outline"
              onClick={switchDebugMode}
              data-testid="chat-detail-multimodel-back"
            >
              <LucideArrowBigLeft />
              <span>{t('common.back')}</span>
            </Button>
          </div>

          <span className="text-2xl">
            {t('chat.multipleModels')} ({chatBoxIds.length}/3)
          </span>
        </header>

        <MultipleChatBox
          chatBoxIds={chatBoxIds}
          controller={controller}
          removeChatBox={removeChatBox}
          addChatBox={addChatBox}
          stopOutputMessage={stopOutputMessage}
          conversation={currentConversation}
        ></MultipleChatBox>
      </section>
    );
  }

  return (
    <RootLayoutContainer>
      {/* Rendered inside the shell this page owns, which is what puts the publish
          within reach of the trail provider. */}
      <BreadcrumbTrail crumbs={breadcrumbTrail} />

      <section className="h-full flex flex-col" data-testid="chat-detail">
        {/* One row filling the viewport: the conversation list and the chat box
            are two panes of the same surface, split by a single hairline. The
            chat box used to sit inside a bordered, rounded card above a 36px
            strip, which read as a picture frame floating in the page. */}
        <article className="flex flex-1 min-h-0">
          <Sessions
            handleConversationCardClick={handleSessionClick}
            visible={sessionsVisible}
            onVisibleChange={setSessionsVisible}
            onOpenSettings={handleOpenSettings}
            onNewConversation={handleStartNewConversation}
            loadingConversationId={
              isLoadingMessages ? conversationId : undefined
            }
          ></Sessions>

          <div className="glass-surface flex min-w-0 flex-1 flex-col overflow-hidden">
            {/* Rendered only while the conversation list is collapsed: an
                expanded list already names the active conversation, and an
                empty header bar would still cost its own height. */}
            {!sessionsVisible && (
              // A fixed-height row: the header can never grow into the
              // transcript, whatever it has to show.
              <header
                className={cn('flex h-12 shrink-0 flex-row items-center px-4', {
                  'border-b border-cable-hairline': hasSingleChatBox,
                })}
              >
                <ConversationHeader
                  sessionId={conversationId}
                  title={currentConversationName}
                  llmId={currentDialog?.llm_id}
                  onModelChange={handleModelChange}
                  datasets={datasetTags}
                  summarizing={summarizing}
                  onExpandSessions={handleExpandSessions}
                  onOpenSettings={handleOpenSettings}
                ></ConversationHeader>
              </header>
            )}

            <div className="min-h-0 flex-1">
              <SingleChatBox
                conversation={currentConversation}
                loading={isLoadingMessages}
              />
            </div>
          </div>

          {/* The one dataset UI, and the one drawer a chat's datasets are read
              and changed in: its field edits the chat, and it is what the page
              raises for a chat that has no datasets at all. */}
          <ChatSettings
            visible={settingsVisible}
            onVisibleChange={(nextVisible) =>
              nextVisible ? showSettings() : hideSettings()
            }
            onOpenMultiModel={handleOpenMultiModel}
            datasetIds={chatDatasetIds}
          ></ChatSettings>
        </article>
      </section>
    </RootLayoutContainer>
  );
}
