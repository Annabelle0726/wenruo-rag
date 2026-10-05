import { Button } from '@/components/ui/button';
import { AlertTriangle } from 'lucide-react';
import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';

type CompilationReadFailureProps = {
  onRetry?: () => void;
  compact?: boolean;
};

/**
 * The panel shown when a knowledge-compilation read failed.
 *
 * Deliberately NOT the empty state. "There is nothing here yet" and "this could not be
 * read" are different answers, and the empty state's own action invites the reader to
 * start a compilation — an invitation that makes no sense while the store holding the
 * compiled pages cannot be asked whether they exist. This panel says what is unknown and
 * offers the only useful action, which is to ask again.
 */
export function CompilationReadFailure({
  onRetry,
  compact,
}: CompilationReadFailureProps) {
  const { t } = useTranslation();

  const handleRetry = useCallback(() => {
    onRetry?.();
  }, [onRetry]);

  return (
    <div
      className="flex-1 min-h-0 flex flex-col items-center justify-center gap-3 border border-dashed border-border-button rounded-xl p-6 text-center"
      data-testid="compilation-read-failure"
    >
      <AlertTriangle className="size-6 text-state-error" />
      <p className="text-text-primary text-base">
        {t('knowledgeCompilation.readFailedTitle')}
      </p>
      {!compact && (
        <p className="text-text-secondary text-sm max-w-md">
          {t('knowledgeCompilation.readFailedDescription')}
        </p>
      )}
      {onRetry && (
        <Button variant="outline" onClick={handleRetry}>
          {t('common.retry')}
        </Button>
      )}
    </div>
  );
}

export default CompilationReadFailure;
