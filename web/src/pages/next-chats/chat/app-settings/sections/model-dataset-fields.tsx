'use client';

import { AvatarNameDescription } from '@/components/avatar-name-description';
import { KnowledgeBaseFormField } from '@/components/knowledge-base-item';
import { LlmSettingFieldItems } from '@/components/llm-setting-items/next';
import { Button } from '@/components/ui/button';
import { prefixName } from '@/utils/form';
import { useTranslation } from 'react-i18next';

type ModelDatasetFieldsProps = {
  prefix?: string;
  /** The embedding page reuses these fields without the assistant identity. */
  hideName?: boolean;
  /**
   * Switches the page into the multi-model comparison view. It lives here rather
   * than in the chat header because it is an action that replaces the whole chat
   * area, not a state of the open conversation.
   */
  onOpenMultiModel?: () => void;
};

/**
 * Assistant identity, chat model with its generation parameters, and the
 * datasets the assistant answers from.
 */
export function ModelDatasetFields({
  prefix = '',
  hideName = false,
  onOpenMultiModel,
}: ModelDatasetFieldsProps) {
  const { t } = useTranslation();
  const llmSettingPrefix = prefixName(prefix, 'llm_setting');

  return (
    <div className="space-y-6">
      {hideName || (
        <AvatarNameDescription
          avatarField={prefixName(prefix, 'icon')}
          nameField={prefixName(prefix, 'name')}
          descriptionField={prefixName(prefix, 'description')}
        />
      )}

      <LlmSettingFieldItems
        prefix={llmSettingPrefix}
        llmId={prefixName(prefix, 'llm_id')}
      ></LlmSettingFieldItems>

      <KnowledgeBaseFormField
        name={prefixName(prefix, 'dataset_ids')}
      ></KnowledgeBaseFormField>

      {onOpenMultiModel && (
        <section className="flex items-center justify-between gap-4 rounded-xl border border-cable-border p-3">
          <div className="min-w-0 space-y-0.5">
            <p className="text-sm text-text-primary">
              {t('chat.multipleModels')}
            </p>
            <p className="text-xs text-text-secondary">
              {t('chat.multipleModelsTip')}
            </p>
          </div>

          <Button
            type="button"
            variant="outline"
            className="shrink-0"
            onClick={onOpenMultiModel}
            data-testid="chat-detail-multimodel-toggle"
          >
            {t('chat.multipleModels')}
          </Button>
        </section>
      )}
    </div>
  );
}
