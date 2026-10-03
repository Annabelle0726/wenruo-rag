import { IArtifact, IWikiCommit } from '@/interfaces/database/dataset';

import { useWikiDetailContent } from './hooks/use-wiki-detail-content';
import { CompilationReadFailure } from './read-failure';
import { WikiCommitModal } from './wiki-commit-modal';
import { WikiDetailEditorPanel } from './wiki-detail-editor-panel';
import { WikiDetailHeader } from './wiki-detail-header';
import { WikiDetailToolbar } from './wiki-detail-toolbar';

type WikiDetailContentProps = {
  selectedArtifact: IArtifact;
  selectedVersion: IWikiCommit | null;
  onSelectVersion: (version: IWikiCommit | null) => void;
  onSelectArtifact: (artifact: IArtifact) => void;
};

export function WikiDetailContent({
  selectedArtifact,
  selectedVersion,
  onSelectVersion,
  onSelectArtifact,
}: WikiDetailContentProps) {
  const {
    isVersionView,
    title,
    displayedArtifact,
    commitDetail,
    canGoBack,
    previousEntryTitle,
    linkNavLoading,
    loading,
    pageError,
    reloadPage,
    editedContent,
    displayedContent,
    referenceDocuments,
    isDirty,
    isOpen,
    open,
    setIsOpen,
    form,
    handleConfirm,
    isUpdating,
    handleCancelEdit,
    handleContentChange,
    handleMarkdownLinkClick,
    handleBack,
    handleExport,
  } = useWikiDetailContent({
    selectedArtifact,
    selectedVersion,
    onSelectVersion,
    onSelectArtifact,
  });

  const toolbar = (
    <WikiDetailToolbar
      isDirty={isDirty}
      selectedArtifact={selectedArtifact}
      selectedVersion={selectedVersion}
      onCancelEdit={handleCancelEdit}
      onCommitClick={open}
      onExport={handleExport}
      onSelectVersion={onSelectVersion}
    />
  );

  // A page whose read failed is not an empty page. The toolbar goes with the
  // editor: committing is only meaningful over content that was actually read.
  const readFailed = Boolean(pageError) && !isVersionView;

  return (
    <section className="size-full min-w-0 flex flex-col">
      <WikiDetailHeader
        title={title}
        displayedArtifact={displayedArtifact}
        commitDetail={commitDetail}
        isVersionView={isVersionView}
        toolbar={readFailed ? null : toolbar}
        canGoBack={canGoBack}
        previousEntryTitle={previousEntryTitle}
        linkNavLoading={linkNavLoading}
        onBack={handleBack}
      />

      {readFailed ? (
        <div className="flex-1 min-h-0 flex px-5 pb-4">
          <CompilationReadFailure onRetry={reloadPage} />
        </div>
      ) : (
        <WikiDetailEditorPanel
          loading={loading}
          editedContent={editedContent}
          displayedContent={displayedContent}
          referenceDocuments={referenceDocuments}
          isVersionView={isVersionView}
          commitDetail={commitDetail}
          onContentChange={handleContentChange}
          onWikiLinkClick={handleMarkdownLinkClick}
        />
      )}

      <WikiCommitModal
        open={isOpen}
        onOpenChange={setIsOpen}
        form={form}
        onConfirm={handleConfirm}
        loading={isUpdating}
      />
    </section>
  );
}
