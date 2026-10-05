import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { LucideCheck, LucideX } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

type InlineRenameInputProps = {
  /** Current name; the draft starts from it and a no-op save cancels. */
  value: string;
  /** Persists the new name. Resolving keeps the editor in place until the caller closes it. */
  onSave: (name: string) => Promise<void>;
  onCancel: () => void;
  saving?: boolean;
  /** Hide the confirm/cancel buttons for tight places (e.g. a sidebar row). */
  showActions?: boolean;
  className?: string;
  inputClassName?: string;
  testId?: string;
};

/**
 * In-place rename editor shared by the chat header title and the conversation
 * list rows: Enter or blur saves, Escape cancels. Cancelling blurs the input
 * first, so a guard keeps that blur from turning into a save.
 */
export function InlineRenameInput({
  value,
  onSave,
  onCancel,
  saving = false,
  showActions = true,
  className,
  inputClassName,
  testId,
}: InlineRenameInputProps) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);
  const skipBlurSaveRef = useRef(false);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const handleChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      setDraft(event.target.value);
    },
    [],
  );

  const handleSave = useCallback(async () => {
    if (skipBlurSaveRef.current) {
      skipBlurSaveRef.current = false;
      return;
    }
    const name = draft.trim();
    if (!name || name === value) {
      onCancel();
      return;
    }
    await onSave(name);
  }, [draft, onCancel, onSave, value]);

  const handleCancel = useCallback(() => {
    skipBlurSaveRef.current = true;
    onCancel();
  }, [onCancel]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLInputElement>) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        handleSave();
      } else if (event.key === 'Escape') {
        event.preventDefault();
        handleCancel();
      }
    },
    [handleCancel, handleSave],
  );

  const iconButtonClass =
    'size-7 shrink-0 rounded-lg p-0 text-text-secondary transition-colors hover:bg-cable-brand-soft hover:text-cable-brand';

  return (
    <span className={cn('flex min-w-0 items-center gap-1', className)}>
      <Input
        ref={inputRef}
        value={draft}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onBlur={handleSave}
        className={cn('h-8 min-w-0', inputClassName)}
        data-testid={testId}
        aria-label={t('common.rename')}
      />
      {showActions && (
        <>
          <Button
            variant="ghost"
            size="icon"
            className={iconButtonClass}
            onClick={handleSave}
            loading={saving}
            aria-label={t('common.save')}
          >
            <LucideCheck className="size-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className={iconButtonClass}
            onClick={handleCancel}
            aria-label={t('common.cancel')}
          >
            <LucideX className="size-4" />
          </Button>
        </>
      )}
    </span>
  );
}
