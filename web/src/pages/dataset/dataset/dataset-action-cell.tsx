import { ConfirmDeleteDialog } from '@/components/confirm-delete-dialog';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { DocumentType } from '@/constants/knowledge';
import { UseRowSelectionType } from '@/hooks/logic-hooks/use-row-selection';
import { useCanManageDataset } from '@/hooks/use-can-manage-dataset';
import { useKnowledgeBaseContext } from '../contexts/knowledge-base-context';
import { useTranslation } from 'react-i18next';
import {
  useSetDocumentStatus,
  useRemoveDocument,
} from '@/hooks/use-document-request';
import { IDocumentInfo } from '@/interfaces/database/document';
import { downloadDatasetDocument } from '@/services/file-manager-service';
import { formatFileSize } from '@/utils/common-util';
import { formatDate } from '@/utils/date';
import { downloadFileFromBlob } from '@/utils/file-util';
import { Download, Eye, EyeOff, Info, PenLine, Trash2 } from 'lucide-react';
import { omit } from 'lodash';
import { ComponentProps, forwardRef, useCallback } from 'react';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import { UseRenameDocumentShowType } from './use-rename-document';
import { useDocumentVisibility } from './use-document-visibility';
import { isDocumentProcessing } from './utils';

const ActionButton = forwardRef<
  HTMLButtonElement,
  ComponentProps<typeof Button> & { label: string }
>(({ label, children, ...props }, ref) => (
  <Tooltip>
    <TooltipTrigger asChild>
      <span className="inline-flex">
        <Button
          ref={ref}
          type="button"
          size="icon-xs"
          variant="ghost"
          aria-label={label}
          {...props}
        >
          {children}
        </Button>
      </span>
    </TooltipTrigger>
    <TooltipContent>{label}</TooltipContent>
  </Tooltip>
));
ActionButton.displayName = 'DocumentActionButton';

const Fields = ['name', 'size', 'type', 'create_time', 'update_time'];

const FunctionMap = {
  size: formatFileSize,
  create_time: formatDate,
  update_time: formatDate,
};

export function DatasetActionCell({
  record,
  showRenameModal,
  setRowSelection,
}: { record: IDocumentInfo } & UseRenameDocumentShowType &
  Pick<UseRowSelectionType, 'setRowSelection'>) {
  const { t } = useTranslation();
  const { knowledgeBase } = useKnowledgeBaseContext();
  const canManage = useCanManageDataset(knowledgeBase);
  const { setDocumentStatus, loading: visibilityLoading } =
    useSetDocumentStatus();
  const { parentHidden, isDocumentHidden } = useDocumentVisibility();
  const hidden = isDocumentHidden(record.status);
  const visibilityLabel = t(
    hidden ? 'listVisibility.restoreFile' : 'listVisibility.hideFile',
  );
  const handleToggleVisibility = useCallback(async () => {
    if (!canManage || parentHidden) return;
    try {
      await setDocumentStatus({
        documentId: record.id,
        datasetId: record.dataset_id,
        status: hidden,
      });
    } catch {
      // The request layer reports errors; retain the server-provided state.
    }
  }, [
    canManage,
    parentHidden,
    hidden,
    record.id,
    record.dataset_id,
    setDocumentStatus,
  ]);
  const { id, type } = record;
  const isRunning = isDocumentProcessing(record);
  const isVirtualDocument = type === DocumentType.Virtual;

  const { removeDocument } = useRemoveDocument();

  const onDownloadDocument = useCallback(async () => {
    try {
      const ext = record.name.split('.').pop()?.toLowerCase() || 'bin';
      const response = await downloadDatasetDocument({
        datasetId: record.dataset_id,
        docId: id,
        ext,
      });
      const blob = new Blob([response.data], {
        type: response.data.type,
      });
      downloadFileFromBlob(blob, record.name);
    } catch (error) {
      console.error('Error downloading document:', error);
    }
  }, [id, record.dataset_id, record.name]);

  const handleRemove = useCallback(async () => {
    const code = await removeDocument(id);
    if (code === 0) {
      setRowSelection((prev) => omit(prev, [id]));
    }
  }, [id, removeDocument, setRowSelection]);

  const handleRename = useCallback(() => {
    showRenameModal(record);
  }, [record, showRenameModal]);

  return (
    <div className="flex gap-2 items-center">
      <ActionButton
        size="icon-xs"
        variant="ghost"
        disabled={isRunning}
        label={t('common.edit')}
        onClick={handleRename}
      >
        <PenLine className="size-[1em]" />
      </ActionButton>
      <Popover>
        <PopoverTrigger asChild>
          <ActionButton
            label={t('listVisibility.fileDetails')}
            disabled={isRunning}
          >
            <Info className="size-[1em]" />
          </ActionButton>
        </PopoverTrigger>
        <PopoverContent className="w-[40vw] max-h-[40vh] overflow-auto">
          <ul className="space-y-2">
            {Object.entries(record)
              .filter(([key]) => Fields.some((x) => x === key))

              .map(([key, value], idx) => {
                return (
                  <li key={idx} className="flex gap-2">
                    {key}:
                    <div>
                      {key in FunctionMap
                        ? FunctionMap[key as keyof typeof FunctionMap](value)
                        : value}
                    </div>
                  </li>
                );
              })}
          </ul>
        </PopoverContent>
      </Popover>

      {isVirtualDocument || (
        <ActionButton
          size="icon-xs"
          variant="ghost"
          label={t('common.download')}
          onClick={onDownloadDocument}
          disabled={isRunning}
        >
          <Download className="size-[1em]" />
        </ActionButton>
      )}
      <ActionButton
        size="icon-xs"
        variant="ghost"
        disabled={!canManage || parentHidden || isRunning || visibilityLoading}
        onClick={handleToggleVisibility}
        label={
          parentHidden ? t('listVisibility.inheritedHidden') : visibilityLabel
        }
        className={cn(hidden && 'text-text-secondary')}
        data-hidden={hidden}
        data-testid="document-toggle-visibility"
      >
        {hidden ? (
          <EyeOff className="size-[1em]" />
        ) : (
          <Eye className="size-[1em]" />
        )}
      </ActionButton>
      <ConfirmDeleteDialog onOk={handleRemove}>
        <ActionButton
          label={t('common.delete')}
          data-testid="document-delete"
          size="icon-xs"
          variant="ghost"
          disabled={isRunning}
        >
          <Trash2 className="size-[1em]" />
        </ActionButton>
      </ConfirmDeleteDialog>
    </div>
  );
}
