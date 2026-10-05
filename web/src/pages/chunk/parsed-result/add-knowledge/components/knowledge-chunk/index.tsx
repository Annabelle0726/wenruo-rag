import {
  useContinuousChunkList,
  useSwitchChunk,
} from '@/hooks/use-chunk-request';
import { LoadingDots } from '@/components/loading-dots';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import ChunkCard from './components/chunk-card';
import CreatingModal from './components/chunk-creating-modal';
import {
  useChangeChunkTextMode,
  useDeleteChunkByIds,
  useGetChunkHighlights,
  useGetSelectedChunk,
  useHandleChunkCardClick,
  useUpdateChunk,
} from './hooks';

import ChunkResultBar from './components/chunk-result-bar';
import CheckboxSets from './components/chunk-result-bar/checkbox-sets';
import DocumentViewSwitch from './components/document-view-switch';
// import DocumentHeader from './components/document-preview/document-header';

import {
  ClaimsPanel,
  type ClaimsPanelState,
  type EvidencePanelState,
  NodeDetailPanel,
} from '@/pages/chunk/representation/components/claim-list';
import { useGetDocumentUrl } from '@/components/document-preview/hooks';
import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import message from '@/components/ui/message';
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable';
import { Spin } from '@/components/ui/spin';
import {
  QueryStringMap,
  useNavigatePage,
} from '@/hooks/logic-hooks/navigate-hooks';
import { getExtension } from '@/utils/document-util';
import { LucideArrowBigLeft } from 'lucide-react';

/**
 * How close to the end of the loaded list the reader has to be before the next
 * block of chunks is requested. Roughly two cards, so the request is in flight
 * before the end of the list is actually reached.
 */
const LOAD_MORE_THRESHOLD_PX = 320;

function Chunk() {
  const [filterChunkIds, setFilterChunkIds] = useState<string[]>([]);
  const [selectedChunkIds, setSelectedChunkIds] = useState<string[]>([]);
  // The artifact tree publishes its claims / evidence content upward; the page
  // renders it as a resizable column between the tree and the chunk list, and
  // shows only two columns while nothing is open.
  const [claimsPanel, setClaimsPanel] = useState<ClaimsPanelState | null>(null);
  const [evidencePanel, setEvidencePanel] = useState<EvidencePanelState | null>(
    null,
  );
  const { removeChunk } = useDeleteChunkByIds();
  // The chunks are ONE continuous list, in document order: search, the
  // enabled/disabled filter and chunk operations all behave as before, but the
  // reader scrolls through the whole document instead of paging through it.
  const {
    chunks,
    documentInfo,
    loading,
    loadingMore,
    hasMore,
    loadMore,
    searchString,
    handleInputChange,
    available,
    handleSetAvailable,
    dataUpdatedAt,
  } = useContinuousChunkList(true, { chunkIds: filterChunkIds });
  const { handleChunkCardClick, selectedChunkId } = useHandleChunkCardClick();

  const { t } = useTranslation();
  const { changeChunkTextMode, textMode } = useChangeChunkTextMode();
  const { switchChunk } = useSwitchChunk();
  const {
    chunkUpdatingLoading,
    onChunkUpdatingOk,
    showChunkUpdatingModal,
    hideChunkUpdatingModal,
    chunkId,
    chunkUpdatingVisible,
    documentId,
  } = useUpdateChunk();
  const { navigateToDataFile, getQueryString } = useNavigatePage();
  const fileUrl = useGetDocumentUrl(false);

  const clearSelectedChunkIds = useCallback(() => {
    setSelectedChunkIds([]);
  }, []);

  // Stable identities: the artifact tree republishes its panel content whenever
  // the claims request settles, so an unstable callback would loop that effect.
  const handleClaimsPanelChange = useCallback(
    (panel: ClaimsPanelState | null) => setClaimsPanel(panel),
    [],
  );
  const handleEvidencePanelChange = useCallback(
    (panel: EvidencePanelState | null) => setEvidencePanel(panel),
    [],
  );

  // A search or a filter changes WHICH chunks are on screen, so a selection made
  // against the previous list is meaningless and is dropped - the same rule the
  // paginated list applied when the page changed, keyed on the query instead of on
  // the page number.
  const displayedQueryRef = useRef('');
  const filterKey = filterChunkIds.join(',');
  useEffect(() => {
    const key = `${searchString}|${available ?? ''}|${filterKey}`;
    if (displayedQueryRef.current === key) return;
    displayedQueryRef.current = key;
    clearSelectedChunkIds();
  }, [searchString, available, filterKey, clearSelectedChunkIds]);

  const selectAllChunk = useCallback(
    (checked: boolean) => {
      // "All" is every chunk this reader has loaded. It used to mean "this page",
      // which was the same thing when the list was paginated; a continuous list
      // has no page, and the loaded set is the only set the reader can see.
      setSelectedChunkIds(checked ? chunks.map((x) => x.chunk_id) : []);
    },
    [chunks],
  );

  const handleSingleCheckboxClick = useCallback(
    (chunkId: string, checked: boolean) => {
      setSelectedChunkIds((previousIds) => {
        const idx = previousIds.findIndex((x) => x === chunkId);
        const nextIds = [...previousIds];
        if (checked && idx === -1) {
          nextIds.push(chunkId);
        } else if (!checked && idx !== -1) {
          nextIds.splice(idx, 1);
        }
        return nextIds;
      });
    },
    [],
  );

  const handleChunkIdsChange = useCallback((chunkIds: string[]) => {
    setFilterChunkIds(chunkIds);
  }, []);

  const showSelectedChunkWarning = useCallback(() => {
    message.warning(t('message.pleaseSelectChunk'));
  }, [t]);

  const handleRemoveChunk = useCallback(async () => {
    if (selectedChunkIds.length > 0) {
      const resCode: number = await removeChunk(selectedChunkIds, documentId);
      if (resCode === 0) {
        clearSelectedChunkIds();
      }
    } else {
      showSelectedChunkWarning();
    }
  }, [
    selectedChunkIds,
    documentId,
    removeChunk,
    showSelectedChunkWarning,
    clearSelectedChunkIds,
  ]);

  const handleSwitchChunk = useCallback(
    async (available?: number, chunkIds?: string[]) => {
      let ids = chunkIds;
      if (!chunkIds) {
        ids = selectedChunkIds;
        if (selectedChunkIds.length === 0) {
          showSelectedChunkWarning();
          return;
        }
      }

      // The list is re-read by the mutation (see `useSwitchChunk`): patching the
      // chunks on screen here would leave the blocks above and below them
      // claiming a state the server no longer has.
      await switchChunk({
        chunk_ids: ids,
        available_int: available,
        doc_id: documentId,
      });
    },
    [switchChunk, documentId, selectedChunkIds, showSelectedChunkWarning],
  );

  const { highlights, setWidthAndHeight } =
    useGetChunkHighlights(selectedChunkId);
  const selectedChunk = useGetSelectedChunk(selectedChunkId);
  const positions = Array.isArray(selectedChunk?.positions)
    ? selectedChunk.positions
    : [];

  // Two columns until the artifact tree opens a claims / evidence panel: the
  // middle column only exists while there is something to show in it.
  const showArtifactDetail = Boolean(claimsPanel || evidencePanel);

  const fileType = useMemo(() => {
    const name = documentInfo?.name || '';
    if (name.includes('.')) {
      return getExtension(name);
    }
    switch (documentInfo?.type) {
      case 'doc':
      case 'visual':
        return documentInfo?.name?.split('.').pop() || documentInfo.type;
      case 'docx':
      case 'txt':
      case 'md':
      case 'mdx':
      case 'pdf':
        return documentInfo.type;
    }
    return 'unknown';
  }, [documentInfo]);

  // The list is virtualized because a document can hold thousands of chunks and
  // only the ones on screen are mounted; the blocks themselves arrive as the
  // reader approaches the end of what is loaded.
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: chunks.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: () => 120, // Estimated card height
    overscan: 5, // Render 5 extra items above/below viewport
  });

  // Reading to within a couple of cards of the end of the loaded list asks for the
  // next block. Loading is never triggered by the list's LENGTH: a short list (a
  // search with three matches) has nothing more to ask for.
  const handleListScroll = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const distanceToEnd =
      container.scrollHeight - container.scrollTop - container.clientHeight;
    if (distanceToEnd <= LOAD_MORE_THRESHOLD_PX) loadMore();
  }, [loadMore]);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container || !hasMore) return;
    // A block that does not fill the region leaves nothing to scroll, so no scroll
    // event would ever ask for the next one: ask here instead.
    if (
      container.scrollHeight <=
      container.clientHeight + LOAD_MORE_THRESHOLD_PX
    ) {
      loadMore();
    }
  }, [chunks.length, hasMore, loadMore]);

  return (
    <main className="h-dvh flex flex-col">
      <PageHeader>
        <Button
          variant="outline"
          onClick={navigateToDataFile(
            getQueryString(QueryStringMap.id) as string,
          )}
        >
          <LucideArrowBigLeft />
          {t('common.back')}
        </Button>
      </PageHeader>

      <Card className="mx-5 mb-5 flex-1 h-0 p-0 bg-transparent shadow-none">
        <CardContent className="p-0 h-full flex flex-row divide-x-0.5 rtl:divide-x-reverse">
          <ResizablePanelGroup direction="horizontal" className="flex-1">
            {/* id + order must be explicit: the middle column mounts after the
                first render, and without them react-resizable-panels orders
                panels by registration, so it would sit AFTER the chunk list
                and its resize handles would drag in the wrong direction. */}
            <ResizablePanel
              id="artifact-tree"
              order={1}
              defaultSize={40}
              minSize={20}
            >
              <article className="h-full flex flex-col">
                <DocumentViewSwitch
                  documentInfo={documentInfo}
                  fileType={fileType}
                  highlights={highlights}
                  setWidthAndHeight={setWidthAndHeight}
                  url={fileUrl}
                  positions={positions}
                  onChunkIdsChange={handleChunkIdsChange}
                  onClaimsPanelChange={handleClaimsPanelChange}
                  onEvidencePanelChange={handleEvidencePanelChange}
                />
              </article>
            </ResizablePanel>

            <ResizableHandle
              withHandle
              className="bg-border-button w-[0.5px]"
            />

            {/* Separate conditionals rather than a fragment: PanelGroup pairs
                each handle with the panels adjacent to it in registration
                order, and a fragment would hide these children from it. */}
            {showArtifactDetail && (
              <ResizablePanel
                id="artifact-detail"
                order={2}
                defaultSize={30}
                minSize={20}
              >
                <article className="h-full flex flex-col">
                  {claimsPanel && (
                    <div className="flex-1 min-h-0">
                      <ClaimsPanel {...claimsPanel} />
                    </div>
                  )}
                  {evidencePanel && (
                    <div className="flex-1 min-h-0">
                      <NodeDetailPanel {...evidencePanel} />
                    </div>
                  )}
                </article>
              </ResizablePanel>
            )}

            {showArtifactDetail && (
              <ResizableHandle
                withHandle
                className="bg-border-button w-[0.5px]"
              />
            )}

            <ResizablePanel
              id="chunk-list"
              order={showArtifactDetail ? 3 : 2}
              defaultSize={60}
              minSize={30}
            >
              <article className="h-full flex flex-col">
                <header className="flex-0 p-5 pb-2.5 border-b-0.5 border-b-border-button">
                  <h2 className="text-[24px]">{t('chunk.chunkResult')}</h2>
                  <div className="text-[14px] text-text-secondary">
                    {t('chunk.chunkResultTip')}
                  </div>
                </header>

                <Spin spinning={loading} className="flex-1 h-0" size="large">
                  <div className="relative @container h-full px-5 pb-5 overflow-hidden flex flex-col">
                    <div
                      className="
                        sticky top-0 z-[1] bg-bg-base space-y-4 py-5
                        @4xl:flex @4xl:justify-between @4xl:items-center
                        @4xl:space-y-0 @4xl:gap-4
                      "
                      role="toolbar"
                    >
                      <ChunkResultBar
                        className="@4xl:order-2"
                        handleInputChange={handleInputChange}
                        searchString={searchString}
                        changeChunkTextMode={changeChunkTextMode}
                        createChunk={showChunkUpdatingModal}
                        available={available}
                        selectAllChunk={selectAllChunk}
                        handleSetAvailable={handleSetAvailable}
                      />

                      <CheckboxSets
                        className="h-8"
                        selectAllChunk={selectAllChunk}
                        switchChunk={handleSwitchChunk}
                        removeChunk={handleRemoveChunk}
                        checked={
                          chunks.length > 0 &&
                          selectedChunkIds.length === chunks.length
                        }
                        selectedChunkIds={selectedChunkIds}
                      />
                    </div>

                    {/* The one continuous scroll region of this page: no page
                        control, no page count and no page size - the whole
                        document is read downward, and the next block of chunks is
                        fetched before the reader reaches the end of the loaded
                        ones. */}
                    <div
                      ref={scrollContainerRef}
                      onScroll={handleListScroll}
                      className="flex-1 overflow-y-auto min-h-0"
                    >
                      <div
                        style={{
                          height: `${virtualizer.getTotalSize()}px`,
                          width: '100%',
                          position: 'relative',
                        }}
                      >
                        {virtualizer.getVirtualItems().map((virtualItem) => {
                          const item = chunks[virtualItem.index];
                          if (!item) return null;
                          return (
                            <div
                              key={item.chunk_id}
                              data-index={virtualItem.index}
                              ref={virtualizer.measureElement}
                              style={{
                                position: 'absolute',
                                top: 0,
                                left: 0,
                                width: '100%',
                                transform: `translateY(${virtualItem.start}px)`,
                              }}
                              className="pb-4"
                            >
                              <ChunkCard
                                item={item}
                                editChunk={showChunkUpdatingModal}
                                checked={selectedChunkIds.some(
                                  (x) => x === item.chunk_id,
                                )}
                                handleCheckboxClick={handleSingleCheckboxClick}
                                switchChunk={handleSwitchChunk}
                                clickChunkCard={handleChunkCardClick}
                                selected={item.chunk_id === selectedChunkId}
                                textMode={textMode}
                                t={dataUpdatedAt}
                              />
                            </div>
                          );
                        })}
                      </div>

                      {/* The next block is on its way. A quiet marker at the end
                          of the list, not a control: there is nothing to click,
                          and nothing to page. */}
                      {loadingMore && (
                        <div
                          className="flex items-center justify-center py-4"
                          data-testid="chunk-list-loading-more"
                        >
                          <LoadingDots />
                        </div>
                      )}
                    </div>
                  </div>
                </Spin>
              </article>
            </ResizablePanel>
          </ResizablePanelGroup>
        </CardContent>
      </Card>

      {chunkUpdatingVisible && (
        <CreatingModal
          doc_id={documentId}
          chunkId={chunkId}
          hideModal={hideChunkUpdatingModal}
          visible={chunkUpdatingVisible}
          loading={chunkUpdatingLoading}
          onOk={onChunkUpdatingOk}
          parserId={documentInfo.parser_id}
        />
      )}
    </main>
  );
}

export default Chunk;
