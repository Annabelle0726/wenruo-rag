import { ConfirmDeleteDialog } from '@/components/confirm-delete-dialog';
import { CardIdentityIcon } from '@/components/card-identity-icon';
import { MoreButton } from '@/components/more-button';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { SearchInput } from '@/components/ui/input';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  useFetchChat,
  useGetChatSearchParams,
  useRemoveSessions,
} from '@/hooks/use-chat-request';
import { cn } from '@/lib/utils';
import {
  LucideCopyX,
  LucideListChecks,
  LucideLoader2,
  LucidePanelLeftClose,
  LucidePencil,
  LucidePin,
  LucidePlus,
  LucideSettings,
  LucideTrash2,
  LucideUndo2,
} from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useChatStreamStore } from '../chat-stream/store';
import { useChatUrlParams } from '../hooks/use-chat-url';
import { useHandleClickConversationCard } from '../hooks/use-click-card';
import { useRenameSession } from '../hooks/use-rename-session';
import {
  useSelectDerivedConversationList,
  useTemporaryConversation,
} from '../hooks/use-select-conversation-list';
import { ConversationDropdown } from './conversation-dropdown';
import { InlineRenameInput } from './inline-rename-input';

type SessionProps = Pick<
  ReturnType<typeof useHandleClickConversationCard>,
  'handleConversationCardClick'
> & {
  /** Owned by the chat page so the header can mirror the collapsed state. */
  visible: boolean;
  onVisibleChange: (visible: boolean) => void;
  /** Opens the chat settings drawer, owned by the chat page. */
  onOpenSettings: () => void;
  /**
   * Starts a new conversation: the page seeds the placeholder the session list
   * renders, and the settings drawer — which is where a conversation's datasets
   * are chosen — raises itself over it when there is nothing to inherit.
   */
  onNewConversation: () => void;
  /**
   * The session whose messages are being fetched. Its row swaps its rename action
   * for a spinner and stops taking clicks, so the rail says "loading" instead of
   * letting the same request be queued twice.
   */
  loadingConversationId?: string;
};
export function Sessions({
  handleConversationCardClick,
  visible,
  onVisibleChange,
  onOpenSettings,
  onNewConversation,
  loadingConversationId,
}: SessionProps) {
  const { t } = useTranslation();
  const {
    list: conversationList,
    handleInputChange,
    searchString,
  } = useSelectDerivedConversationList();
  const { removeTemporaryConversation } = useTemporaryConversation();
  const { data } = useFetchChat();
  const switchVisible = useCallback(() => {
    onVisibleChange(!visible);
  }, [onVisibleChange, visible]);
  const { removeSessions } = useRemoveSessions();
  const { setConversationBoth } = useChatUrlParams();
  const { conversationId } = useGetChatSearchParams();
  const removeStreamSessions = useChatStreamStore(
    (state) => state.removeSessions,
  );

  const { renameSession, loading: renaming } = useRenameSession();
  // Id of the row being renamed in place; the input replaces that row's label.
  const [renamingConversationId, setRenamingConversationId] = useState('');

  const handleStartRenaming = useCallback((id: string) => {
    setRenamingConversationId(id);
  }, []);

  const handleCancelRenaming = useCallback(() => {
    setRenamingConversationId('');
  }, []);

  const handleRenameConversation = useCallback(
    async (id: string, name: string) => {
      const renamed = await renameSession({ sessionId: id, name });
      if (renamed) {
        setRenamingConversationId('');
      }
    },
    [renameSession],
  );

  // Selection mode state
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Toggle selection mode (click batch delete icon)
  const toggleSelectionMode = useCallback(() => {
    setSelectionMode(true);
    setSelectedIds(new Set());
  }, []);

  // Exit selection mode (click return icon)
  const exitSelectionMode = useCallback(() => {
    setSelectionMode(false);
    setSelectedIds(new Set());
  }, []);

  // Toggle single item selection
  const toggleSelection = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(id)) {
        newSet.delete(id);
      } else {
        newSet.add(id);
      }
      return newSet;
    });
  }, []);

  // Selected items that are still visible under the current search filter.
  // Batch deletion and the selected count must act on this set — selectedIds
  // alone would include items filtered out of view by the search.
  const visibleSelectedIds = useMemo(
    () =>
      conversationList.filter((x) => selectedIds.has(x.id)).map((x) => x.id),
    [conversationList, selectedIds],
  );

  // Toggle select all
  const toggleSelectAll = useCallback(() => {
    setSelectedIds((prev) => {
      const allVisibleSelected =
        conversationList.length > 0 &&
        conversationList.every((x) => prev.has(x.id));
      if (allVisibleSelected) {
        return new Set();
      }
      return new Set(conversationList.map((x) => x.id));
    });
  }, [conversationList]);

  // Batch delete
  const handleBatchDelete = useCallback(async () => {
    if (visibleSelectedIds.length === 0) {
      return;
    }

    const currentConversationDeleted = conversationId
      ? visibleSelectedIds.includes(conversationId)
      : false;
    const temporaryIdSet = new Set(
      conversationList.filter((item) => item.is_new).map((item) => item.id),
    );
    const persistedIds: string[] = [];
    const removedTemporaryIds: string[] = [];

    visibleSelectedIds.forEach((id) => {
      if (temporaryIdSet.has(id)) {
        removeTemporaryConversation(id);
        removedTemporaryIds.push(id);
      } else {
        persistedIds.push(id);
      }
    });

    let removeCode = -1;
    if (persistedIds.length > 0) {
      removeCode = await removeSessions(persistedIds);
    }

    // Purge the streaming store for every id that actually went away, aborting
    // any in-flight stream so it can't keep writing into a dead session.
    removeStreamSessions([
      ...removedTemporaryIds,
      ...(removeCode === 0 ? persistedIds : []),
    ]);

    if (currentConversationDeleted && conversationId) {
      const currentIsTemporary = temporaryIdSet.has(conversationId);
      const currentPersistedDeleted =
        persistedIds.includes(conversationId) && removeCode === 0;
      if (currentIsTemporary || currentPersistedDeleted) {
        setConversationBoth('', '');
      }
    }
    exitSelectionMode();
  }, [
    visibleSelectedIds,
    conversationId,
    conversationList,
    setConversationBoth,
    removeTemporaryConversation,
    removeSessions,
    removeStreamSessions,
    exitSelectionMode,
  ]);

  const selectedCount = visibleSelectedIds.length;

  if (!visible) {
    return (
      <div className="glass-surface flex w-14 shrink-0 justify-center border-r border-cable-hairline p-3">
        <Button
          variant="transparent"
          size="icon-sm"
          className="border-0"
          onClick={switchVisible}
          data-testid="chat-detail-sessions-open"
        >
          {/* The assistant's card mark, not the first character of its name. */}
          <CardIdentityIcon
            kind="chat"
            avatar={data.icon}
            className="cursor-pointer"
          />
        </Button>
      </div>
    );
  }

  return (
    <aside
      // Flush against the chat box: the two panes meet at one hairline instead
      // of a rounded floating card with a 24px gutter around it. One column
      // with a single gap value, so the rail reads as evenly spaced blocks.
      // The 12px top is the one margin under the header: the 20px it had was a
      // second one, and it pushed this rail's first row below the transcript's
      // content beside it. Both panes now start their content on the same line.
      className="glass-surface flex h-full w-[296px] shrink-0 flex-col gap-2 border-r border-cable-hairline px-5 pb-5 pt-3"
      role="complementary"
      data-testid="chat-detail-sessions"
    >
      <header className="flex items-center text-base justify-between gap-4">
        <div className="flex gap-3 items-center min-w-0">
          {/* Same component and same props as `ChatCard`, so the assistant wears
              one mark on its card and in the header of the page that card opens. */}
          <CardIdentityIcon kind="chat" avatar={data.icon} />

          <span className="flex-1 truncate">{data.name}</span>
        </div>

        {/* Settings: opens the slide-over panel. It replaces the embed-into-site
            entry point, which this deployment does not use. */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              onClick={onOpenSettings}
              variant="transparent"
              size="icon-xs"
              className="border-0"
              aria-label={t('chat.chatSetting')}
              data-testid="chat-settings"
            >
              <LucideSettings className="size-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t('chat.chatSetting')}</TooltipContent>
        </Tooltip>

        <Button
          variant="transparent"
          size="icon-sm"
          className="border-0 ml-auto"
          onClick={switchVisible}
          data-testid="chat-detail-sessions-close"
        >
          <LucidePanelLeftClose />
        </Button>
      </header>

      <div className="flex justify-between items-center">
        <div className="flex items-center gap-3">
          <span className="text-base font-bold">{t('chat.conversations')}</span>
          <data
            className="text-text-secondary text-xs"
            value={conversationList.length}
          >
            {conversationList.length}
          </data>
        </div>

        <div className="flex items-center gap-2">
          {selectionMode ? (
            // Exit selection mode
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={exitSelectionMode}
              data-testid="chat-detail-session-selection-exit"
            >
              <LucideUndo2 size={16} />
            </Button>
          ) : (
            // New conversation: the placeholder the page seeds, which the
            // settings drawer then guides the datasets of when it has none to
            // inherit.
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={onNewConversation}
              aria-label={t('chat.newConversation')}
              data-testid="chat-detail-session-new"
            >
              <LucidePlus className="h-4 w-4" />
            </Button>
          )}

          {selectionMode && selectedCount > 0 ? (
            // Delete selected items
            <ConfirmDeleteDialog
              onOk={handleBatchDelete}
              title={t('chat.batchDeleteSessions')}
              content={{
                title: t('chat.deleteSelectedConfirm', {
                  count: selectedCount,
                }),
              }}
              testId="chat-detail-session-batch-delete-dialog"
              confirmButtonTestId="chat-detail-session-batch-delete-confirm"
              cancelButtonTestId="chat-detail-session-batch-delete-cancel"
            >
              <Button
                variant="delete"
                size="icon-xs"
                data-testid="chat-detail-session-batch-delete"
              >
                <LucideTrash2 />
              </Button>
            </ConfirmDeleteDialog>
          ) : (
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={selectionMode ? toggleSelectAll : toggleSelectionMode}
              data-testid={
                selectionMode
                  ? 'chat-detail-session-select-all'
                  : 'chat-detail-session-selection-enable'
              }
            >
              {selectionMode ? <LucideListChecks /> : <LucideCopyX />}
            </Button>
          )}
        </div>
      </div>

      <div role="search">
        <SearchInput
          onChange={handleInputChange}
          value={searchString}
          data-testid="chat-detail-session-search"
        ></SearchInput>
      </div>

      {/* The list starts directly under the search box and grows downwards, so
          the first conversation — and the "new conversation" entry above it —
          stay where the eye expects them. Centring this block left the list
          floating in the middle of the rail with a void under the search box. */}
      <div className="flex min-h-0 flex-1 flex-col justify-start overflow-y-auto">
        {selectionMode ? (
          <ul className="space-y-2" role="listbox" aria-multiselectable>
            {conversationList.map((x) => (
              <li
                key={x.id}
                className="py-2"
                role="option"
                aria-selected={selectedIds.has(x.id)}
                data-session-id={x.id}
              >
                <label className="flex items-center gap-2">
                  <Checkbox
                    checked={selectedIds.has(x.id)}
                    onCheckedChange={() => toggleSelection(x.id)}
                    data-testid="chat-detail-session-checkbox"
                    data-session-id={x.id}
                  />

                  <span className="truncate">{x.name}</span>
                </label>
              </li>
            ))}
          </ul>
        ) : (
          <nav aria-label={t('chat.conversations')}>
            <ul className="space-y-2">
              {conversationList.map((x) => {
                const isRowLoading = loadingConversationId === x.id;

                return (
                  <li
                    key={x.id}
                    // A pinned row wears a surface of its own, so it reads as pinned
                    // before the pointer goes anywhere near it; the open one swaps
                    // that surface for the brand bar on its leading edge, which the
                    // selected highlight alone would not say.
                    //
                    // `bg-cable-surface-muted` rather than `bg-cable-surface/60`: the
                    // cable tokens are plain `var()` colours, and Tailwind v3 emits no
                    // rule at all for an opacity modifier on one of those, so the
                    // row would have come out with no background. The muted token is
                    // the surface a step up from the page — translucent white in the
                    // light theme, #1b2129 against #161b22 in the dark one.
                    className={cn(
                      'group pr-3 flex items-center gap-1 rounded-lg',
                      'aria-selected:bg-bg-card has-[>button:focus-visible]:bg-bg-card',
                      x.is_pinned &&
                        (conversationId === x.id
                          ? 'border-l-2 border-l-cable-accent'
                          : 'border border-cable-hairline bg-cable-surface-muted'),
                    )}
                    aria-selected={conversationId === x.id}
                    aria-busy={isRowLoading || undefined}
                    data-loading={isRowLoading ? 'true' : undefined}
                  >
                    {renamingConversationId === x.id ? (
                      <InlineRenameInput
                        value={x.name}
                        onSave={(name) => handleRenameConversation(x.id, name)}
                        onCancel={handleCancelRenaming}
                        saving={renaming}
                        showActions={false}
                        className="flex-1 px-2 py-1"
                        inputClassName="text-sm"
                        testId="chat-detail-session-rename-input"
                      />
                    ) : (
                      <>
                        <button
                          type="button"
                          className="focus-visible:outline-none px-3 py-2 text-left flex min-w-0 flex-1 items-center gap-1.5"
                          onClick={() =>
                            handleConversationCardClick(x.id, x.is_new)
                          }
                          // The row being fetched already owns the request: a second
                          // click can only queue the same id again.
                          disabled={isRowLoading}
                          onDoubleClick={() => handleStartRenaming(x.id)}
                          data-testid="chat-detail-session-item"
                          data-session-id={x.id}
                        >
                          {/* Inside the button, so the marker never becomes a
                            smaller target than the row it labels. */}
                          {x.is_pinned ? (
                            <LucidePin
                              aria-hidden
                              data-testid="chat-detail-session-pin-marker"
                              className="size-3.5 shrink-0 text-cable-accent"
                            />
                          ) : null}
                          <span className="min-w-0 flex-1 truncate">
                            {x.name}
                          </span>
                        </button>

                        {/* The row's own loading mark: the fetch is what the spinner
                          reports, so it takes the slot the rename action leaves
                          empty and hands it back once the messages land. */}
                        {isRowLoading ? (
                          <span
                            className="flex size-7 shrink-0 items-center justify-center"
                            data-testid="chat-detail-session-loading"
                            data-session-id={x.id}
                          >
                            <LucideLoader2 className="size-3.5 animate-spin text-cable-brand" />
                          </span>
                        ) : (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-7 shrink-0 rounded-lg p-0 text-text-secondary opacity-0 transition-colors group-hover:opacity-100 hover:bg-cable-brand-soft hover:text-cable-brand"
                            onClick={() => handleStartRenaming(x.id)}
                            aria-label={t('common.rename')}
                            data-testid="chat-detail-session-rename"
                            data-session-id={x.id}
                          >
                            <LucidePencil className="size-3.5" />
                          </Button>
                        )}
                      </>
                    )}

                    <ConversationDropdown
                      conversation={x}
                      removeTemporaryConversation={removeTemporaryConversation}
                    >
                      <MoreButton
                        data-testid="chat-detail-session-actions"
                        data-session-id={x.id}
                      ></MoreButton>
                    </ConversationDropdown>
                  </li>
                );
              })}
            </ul>
          </nav>
        )}
      </div>
    </aside>
  );
}
