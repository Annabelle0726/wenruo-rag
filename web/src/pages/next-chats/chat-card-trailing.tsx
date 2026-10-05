import { useTranslation } from 'react-i18next';

/**
 * A chat card's trailing content: one pill carrying the chat's total messages.
 *
 * `--cable-surface` keeps the pill readable on the translucent glass card in both
 * themes, and the hairline rim matches the other pills in the app.
 *
 * It owns the card's whole right edge, so a chat that has no count yet renders
 * nothing at all rather than a placeholder: with no second item in the card's
 * row, the flex gap collapses and the text column keeps the width the pill would
 * have taken.
 */
const COUNT_CLASS =
  'inline-flex shrink-0 items-center rounded-full border border-accent-primary/20 bg-accent-color-soft px-2.5 py-0.5 font-mono text-xs tabular-nums text-cable-brand';

export function ChatCardTrailing({ messageCount }: { messageCount?: number }) {
  const { t } = useTranslation();

  if (!messageCount) {
    return null;
  }

  return (
    <span className={COUNT_CLASS} data-testid="chat-message-count">
      {t('chat.messageCount', { total: messageCount })}
    </span>
  );
}
