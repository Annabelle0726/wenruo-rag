import { ModelTreeSelect } from '@/components/model-tree-select';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import {
  LucideChevronDown,
  LucideLoader,
  LucidePanelLeftOpen,
  LucidePencil,
  LucideSettings,
} from 'lucide-react';
import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useRenameSession } from '../hooks/use-rename-session';
import { DatasetTag, DatasetTags } from './dataset-tags';
import { InlineRenameInput } from './inline-rename-input';

type ConversationHeaderProps = {
  sessionId?: string;
  /** Conversation title: the raw first question until it is summarised or renamed. */
  title: string;
  /** Model the conversation answers with, switchable from the name dropdown. */
  llmId?: string;
  onModelChange?: (llmId: string) => void;
  /**
   * Effective datasets of the open conversation — its own binding, else the
   * assistant's set — already named, shown as tags. Named by the page because
   * resolving them needs the dataset request, which this leaf row must not
   * carry.
   */
  datasets?: DatasetTag[];
  /** Reported by the page, which owns the titling this header only displays. */
  summarizing?: boolean;
  /** Re-opens the conversation list this header only renders without. */
  onExpandSessions?: () => void;
  /**
   * Opens the chat settings drawer. It is where the conversation's datasets are
   * changed, so it is the target of both the settings entry and the tags, and it
   * is reachable here only because the conversation list (and its own settings
   * button) is collapsed.
   */
  onOpenSettings?: () => void;
};

/**
 * Chat header for one conversation, mounted by the page only while the
 * conversation list is collapsed.
 *
 * One fixed-height row, by design: the assistant/conversation name with the
 * controls that belong to it (`chevron` opens the model dropdown, the title
 * renames), the tags naming the datasets this conversation retrieves from, and
 * on the right only the settings entry and the control that re-opens the
 * conversation list. Anything else (the multi-model view, the retrieval and
 * prompt settings) lives in the settings drawer, so the row can never grow into
 * the transcript. The tags open that same drawer, where their datasets are
 * changed — there is no separate picker.
 *
 * The dropdown is a popover anchored under the row rather than an expanding
 * section: the header keeps its height, so the messages below never move.
 */
export function ConversationHeader({
  sessionId,
  title,
  llmId,
  onModelChange,
  datasets,
  summarizing = false,
  onExpandSessions,
  onOpenSettings,
}: ConversationHeaderProps) {
  const { t } = useTranslation();
  const [modelOpen, setModelOpen] = useState(false);
  const [editing, setEditing] = useState(false);

  const { renameSession, loading: renaming } = useRenameSession();

  const handleModelOpenChange = useCallback((open: boolean) => {
    setModelOpen(open);
  }, []);

  const handleModelChange = useCallback(
    (nextLlmId: string) => {
      setModelOpen(false);
      onModelChange?.(nextLlmId);
    },
    [onModelChange],
  );

  const handleStartEditing = useCallback(() => {
    setEditing(true);
  }, []);

  const handleCancelEditing = useCallback(() => {
    setEditing(false);
  }, []);

  const handleSaveTitle = useCallback(
    async (name: string) => {
      // A conversation that only exists in the browser is created by naming it,
      // so the title the user types is never dropped.
      const renamed = await renameSession({ sessionId, name });
      if (renamed) {
        setEditing(false);
      }
    },
    [renameSession, sessionId],
  );

  const iconButtonClass =
    'size-7 shrink-0 rounded-lg p-0 text-text-secondary transition-colors hover:bg-cable-brand-soft hover:text-cable-brand';

  return (
    <header className="flex min-w-0 items-center justify-between gap-2">
      <div className="group flex min-w-0 items-center gap-1">
        <Popover open={modelOpen} onOpenChange={handleModelOpenChange}>
          <PopoverTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className={iconButtonClass}
              aria-expanded={modelOpen}
              aria-label={t('chat.model')}
              title={t('chat.model')}
              data-testid="chat-detail-header-toggle"
            >
              <LucideChevronDown
                className={cn(
                  'size-4 transition-transform',
                  modelOpen && 'rotate-180',
                )}
              />
            </Button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-80 space-y-2 p-3">
            <p className="text-xs text-text-secondary">{t('chat.model')}</p>
            <ModelTreeSelect
              modelTypes={['chat', 'vision']}
              value={llmId}
              onChange={handleModelChange}
              testId="chat-detail-header-model"
            />
          </PopoverContent>
        </Popover>

        {editing ? (
          <InlineRenameInput
            value={title}
            onSave={handleSaveTitle}
            onCancel={handleCancelEditing}
            saving={renaming}
            inputClassName="max-w-[min(60vw,32rem)] text-base"
            testId="chat-detail-title-input"
          />
        ) : (
          <>
            <button
              type="button"
              onClick={handleStartEditing}
              title={t('common.rename')}
              data-testid="chat-detail-title"
              className="min-w-0 truncate rounded-lg px-1.5 py-1 text-base font-medium text-text-primary transition-colors hover:bg-cable-brand-soft"
            >
              {title}
            </button>

            <Button
              variant="ghost"
              size="icon"
              className={cn(
                iconButtonClass,
                'opacity-0 group-hover:opacity-100',
              )}
              onClick={handleStartEditing}
              aria-label={t('common.rename')}
              data-testid="chat-detail-title-edit"
            >
              <LucidePencil className="size-3.5" />
            </Button>
          </>
        )}

        {summarizing && (
          <span
            className="flex shrink-0 items-center text-cable-muted"
            title={t('chat.summarizingTitle')}
          >
            <LucideLoader className="size-3.5 animate-spin" />
          </span>
        )}
      </div>

      {/* The conversation's retrieval scope, between the title it belongs to and
          the controls on the right: the tags say where the answers come from
          without costing the row any height. A tag opens the same settings
          drawer as the gear beside it, which is where the selection changes. */}
      {onOpenSettings && datasets && (
        <DatasetTags
          datasets={datasets}
          onOpenSettings={onOpenSettings}
        ></DatasetTags>
      )}

      <div className="flex shrink-0 items-center gap-2">
        {onOpenSettings && (
          <Button
            variant="ghost"
            size="icon"
            className={iconButtonClass}
            onClick={onOpenSettings}
            aria-label={t('chat.chatSetting')}
            title={t('chat.chatSetting')}
            data-testid="chat-settings-header"
          >
            <LucideSettings className="size-4" />
          </Button>
        )}

        {onExpandSessions && (
          <Button
            variant="ghost"
            size="icon"
            className={iconButtonClass}
            onClick={onExpandSessions}
            aria-label={t('chat.showConversations')}
            title={t('chat.showConversations')}
            data-testid="chat-detail-sessions-open-header"
          >
            <LucidePanelLeftOpen className="size-4" />
          </Button>
        )}
      </div>
    </header>
  );
}
