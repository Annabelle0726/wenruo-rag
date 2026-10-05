import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';

/** Message-shaped placeholders, alternating sides so the block reads as a transcript. */
const PlaceholderRows = [
  { align: 'items-start', avatar: true, widths: ['w-2/5', 'w-3/5'] },
  { align: 'items-end', avatar: false, widths: ['w-1/3'] },
  { align: 'items-start', avatar: true, widths: ['w-1/4', 'w-2/3', 'w-1/2'] },
];

/**
 * The transcript's loading screen.
 *
 * Shown the moment a conversation is picked and removed when its messages land, so
 * the pane answers the click instead of standing empty. It also replaces the
 * previous conversation's messages during the wait, which is what keeps a slow
 * request from looking like a successful switch to the wrong session.
 */
export function MessageSkeleton({ className }: { className?: string }) {
  const { t } = useTranslation();

  return (
    <div
      className={cn('flex flex-col gap-6', className)}
      role="status"
      aria-busy="true"
      aria-live="polite"
      data-testid="chat-messages-loading"
    >
      <span className="sr-only">{t('chat.loadingSession')}</span>

      {PlaceholderRows.map((row, index) => (
        <div
          key={index}
          className={cn('flex gap-3', row.align)}
          aria-hidden="true"
        >
          {row.avatar && <Skeleton className="size-8 shrink-0 rounded-none" />}
          <div className="flex w-full flex-col gap-2">
            {row.widths.map((width) => (
              <Skeleton key={width} className={cn('h-4 rounded-none', width)} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
