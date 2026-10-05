import {
  ConfirmDeleteDialog,
  ConfirmDeleteDialogNode,
} from '@/components/confirm-delete-dialog';
import { FileIcon } from '@/components/icon-font';
import NewDocumentLink from '@/components/new-document-link';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { UseRowSelectionType } from '@/hooks/logic-hooks/use-row-selection';
import { useDownloadFile } from '@/hooks/use-file-request';
import { IFile } from '@/interfaces/database/file-manager';
import { cn } from '@/lib/utils';
import { useIsGoBackend } from '@/utils/backend-variant';
import {
  getExtension,
  isSupportedPreviewDocumentType,
} from '@/utils/document-util';
import { CellContext } from '@tanstack/react-table';
import { t } from 'i18next';
import {
  ArrowDownToLine,
  EllipsisVertical,
  Eye,
  FolderInput,
  FolderPen,
  Link2,
  Trash2,
} from 'lucide-react';
import { useCallback } from 'react';
import {
  UseHandleConnectToKnowledgeReturnType,
  UseRenameCurrentFileReturnType,
} from './hooks';
import { useHandleDeleteFile } from './use-delete-file';
import { UseMoveDocumentShowType } from './use-move-file';
import { isFolderType, isKnowledgeBaseType } from './util';

type IProps = Pick<CellContext<IFile, unknown>, 'row'> &
  Pick<UseHandleConnectToKnowledgeReturnType, 'showConnectToKnowledgeModal'> &
  Pick<UseRenameCurrentFileReturnType, 'showFileRenameModal'> &
  Pick<UseRowSelectionType, 'setRowSelection'> &
  UseMoveDocumentShowType;

export function ActionCell({
  row,
  showConnectToKnowledgeModal,
  showFileRenameModal,
  showMoveFileModal,
  setRowSelection,
}: IProps) {
  const record = row.original;
  const documentId = record.id;
  const name: string = row.getValue('name');
  const type = record.type;

  const { downloadFile } = useDownloadFile();
  const isSkillsEnabled = useIsGoBackend();
  const isFolder = isFolderType(record.type);
  const isSkillsFolder =
    isSkillsEnabled && isFolder && record.name.toLowerCase() === 'skills';
  const extension = getExtension(record.name);
  const isKnowledgeBase = isKnowledgeBaseType(record.source_type);

  const handleShowConnectToKnowledgeModal = useCallback(() => {
    showConnectToKnowledgeModal(record);
  }, [record, showConnectToKnowledgeModal]);

  const onDownloadDocument = useCallback(() => {
    downloadFile({
      id: documentId,
      filename: record.name,
    });
  }, [documentId, downloadFile, record.name]);

  const handleShowFileRenameModal = useCallback(() => {
    showFileRenameModal(record);
  }, [record, showFileRenameModal]);

  const handleShowMoveFileModal = useCallback(() => {
    showMoveFileModal([record.id]);
  }, [record, showMoveFileModal]);

  const { handleRemoveFile } = useHandleDeleteFile();

  const onRemoveFile = useCallback(async () => {
    const code = await handleRemoveFile([documentId]);
    if (code === 0) {
      // Prune the deleted file from the multi-selection so the bulk
      // operation bar doesn't keep counting it.
      setRowSelection((previous) => {
        const next = { ...previous };
        delete next[documentId];
        return next;
      });
    }
  }, [handleRemoveFile, documentId, setRowSelection]);

  if (isSkillsFolder) {
    return null;
  }

  return (
    <section className="flex items-center gap-2 text-content-tertiary">
      {isKnowledgeBase || (
        <Button
          variant="transparent"
          className="size-8 rounded-full border-none text-content-secondary transition-colors duration-200 hover:bg-cable-nav-active-bg hover:text-cable-accent"
          size="icon-sm"
          onClick={handleShowConnectToKnowledgeModal}
        >
          <Link2 />
        </Button>
      )}
      {isKnowledgeBase || (
        <Button
          variant="transparent"
          className="size-8 rounded-full border-none text-content-secondary transition-colors duration-200 hover:bg-cable-nav-active-bg hover:text-cable-accent"
          size="icon-sm"
          onClick={handleShowMoveFileModal}
        >
          <FolderInput />
        </Button>
      )}
      {isKnowledgeBase || (
        <Button
          variant="transparent"
          className="size-8 rounded-full border-none text-content-secondary transition-colors duration-200 hover:bg-cable-nav-active-bg hover:text-cable-accent"
          size="icon-sm"
          onClick={handleShowFileRenameModal}
        >
          <FolderPen />
        </Button>
      )}
      {isFolder || (
        <Button
          variant="transparent"
          className="size-8 rounded-full border-none text-content-secondary transition-colors duration-200 hover:bg-cable-nav-active-bg hover:text-cable-accent"
          size="icon-sm"
          onClick={onDownloadDocument}
        >
          <ArrowDownToLine />
        </Button>
      )}

      {isSupportedPreviewDocumentType(extension) && (
        <NewDocumentLink
          documentId={documentId}
          documentName={record.name}
          resource="files"
          className="text-text-sub-title-invert"
        >
          <Button
            variant="transparent"
            className="size-8 rounded-full border-none text-content-secondary transition-colors duration-200 hover:bg-cable-nav-active-bg hover:text-cable-accent"
            size="icon-sm"
          >
            <Eye />
          </Button>
        </NewDocumentLink>
      )}

      {/* The overflow menu is the row's guaranteed action point: every other
          button is conditional (a folder cannot be renamed from here, a
          knowledge-base entry cannot be moved, a previewable type needs the
          previewer), so without it a knowledge-base row had no visible action at
          all at rest. */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="transparent"
            className="size-8 rounded-full border-none text-content-secondary transition-colors duration-200 hover:bg-cable-nav-active-bg hover:text-cable-accent"
            size="icon-sm"
            data-testid="file-actions-more"
          >
            <EllipsisVertical />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {isKnowledgeBase || (
            <DropdownMenuItem onClick={handleShowMoveFileModal}>
              {t('common.move')}
            </DropdownMenuItem>
          )}
          {isKnowledgeBase || isFolder || (
            <DropdownMenuItem onClick={handleShowFileRenameModal}>
              {t('common.rename')}
            </DropdownMenuItem>
          )}
          {isFolder || (
            <DropdownMenuItem onClick={onDownloadDocument}>
              {t('common.download')}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {isKnowledgeBase || (
        <ConfirmDeleteDialog
          onOk={onRemoveFile}
          title={t('deleteModal.delFile')}
          content={{
            node: (
              <ConfirmDeleteDialogNode>
                <div className="flex items-center gap-2 text-text-secondary">
                  <span className="size-4">
                    <FileIcon name={name} type={type}></FileIcon>
                  </span>
                  <span
                    className={cn('truncate text-xs text-wrap', {
                      ['cursor-pointer']: isFolder,
                    })}
                  >
                    {name}
                  </span>
                </div>
              </ConfirmDeleteDialogNode>
            ),
          }}
        >
          <Button
            variant="transparent"
            className="size-8 rounded-full border-none text-content-secondary transition-colors duration-200 hover:bg-cable-nav-active-bg hover:text-cable-accent"
            size="icon-sm"
          >
            <Trash2 />
          </Button>
        </ConfirmDeleteDialog>
      )}
    </section>
  );
}
