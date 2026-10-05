/*
 *  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 */

import ModelServiceUnavailable from '@/components/model-service-unavailable';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Progress } from '@/components/ui/progress';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { IModalProps } from '@/interfaces/common';
import { ModelServiceErrorType } from '@/utils/model-service-error';
import { Maximize2, X } from 'lucide-react';
import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { usePendingMindMap } from './hooks';
import MindMapViewer from './mind-map-viewer';

interface IProps extends IModalProps<any> {
  data: any;
  /** Set when the vector service refused the query the map is built from. */
  errorType?: ModelServiceErrorType | null;
}

const MindMapSheet = ({
  data,
  errorType,
  hideModal,
  loading,
  visible,
}: IProps) => {
  const { t } = useTranslation();
  const percent = usePendingMindMap();
  const [isFullscreen, setIsFullscreen] = useState(false);
  // An empty tree (no children) means the backend honestly found nothing to
  // map. Render an explicit empty state instead of a ghost "root" node.
  const isEmptyMindMap =
    !data || !Array.isArray(data.children) || data.children.length === 0;

  const handleClose = useCallback(() => {
    setIsFullscreen(false);
    hideModal?.();
  }, [hideModal]);

  const handleOpenFullscreen = useCallback(() => {
    setIsFullscreen(true);
  }, []);

  const emptyState = (
    <div className="bg-bg-card rounded-lg w-full h-full flex items-center justify-center">
      <p className="text-text-secondary">
        {t('knowledgeCompilation.noStructureMindmap')}
      </p>
    </div>
  );

  return (
    <>
      <Sheet open={visible} modal={false}>
        <SheetContent
          className="top-24 p-0 flex flex-col gap-0 h-auto"
          closeIcon={false}
        >
          <SheetHeader className="border-b py-2 px-4">
            <SheetTitle className="hidden"></SheetTitle>
            <div className="flex w-full justify-between items-center">
              <div className="text-text-primary font-medium text-base">
                {t('chunk.mind')}
              </div>
              <div className="flex items-center gap-1">
                {/* The drawer is a narrow rail beside the answer, which is the
                    worst place to read a wide map. This hands it the window
                    instead, without losing the answer behind it. */}
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={handleOpenFullscreen}
                  aria-label={t('chunk.mindFullscreen')}
                  title={t('chunk.mindFullscreen')}
                  data-testid="mindmap-fullscreen-open"
                >
                  <Maximize2 className="size-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={handleClose}
                  aria-label={t('common.close')}
                  title={t('common.close')}
                  data-testid="mindmap-close"
                >
                  <X className="size-4" />
                </Button>
              </div>
            </div>
          </SheetHeader>
          <div className="flex-1 p-4 overflow-hidden">
            {loading && (
              <div className="rounded-lg w-full h-full">
                <Progress value={percent} className="h-1 flex-1 min-w-10" />
              </div>
            )}
            {!loading && errorType && (
              // The map is built from retrieved passages, so a refused query is
              // why there is nothing to draw — not a question with no structure.
              <ModelServiceUnavailable
                errorType={errorType}
                title={t('search.embeddingUnavailable')}
                className="h-full"
              ></ModelServiceUnavailable>
            )}
            {!loading && !errorType && isEmptyMindMap && emptyState}
            {!loading && !errorType && !isEmptyMindMap && (
              <div className="h-full w-full">
                <MindMapViewer data={data}></MindMapViewer>
              </div>
            )}
          </div>
        </SheetContent>
      </Sheet>

      <Dialog open={isFullscreen} onOpenChange={setIsFullscreen}>
        <DialogContent
          className="flex h-[85vh] w-[90vw] max-w-[1440px] flex-col gap-0 p-0"
          data-testid="mindmap-fullscreen-dialog"
        >
          <DialogHeader className="-mx-0 -mt-0 flex-row items-center border-b border-border-button px-4 py-3 text-left">
            <DialogTitle className="text-base font-medium">
              {t('chunk.mind')}
            </DialogTitle>
          </DialogHeader>
          <div className="min-h-0 flex-1 p-4">
            {errorType ? (
              <ModelServiceUnavailable
                errorType={errorType}
                title={t('search.embeddingUnavailable')}
                className="h-full"
              ></ModelServiceUnavailable>
            ) : isEmptyMindMap ? (
              emptyState
            ) : (
              // Mounted only while open: a second G6 canvas behind a closed
              // dialog would lay the same tree out for nobody.
              <MindMapViewer data={data}></MindMapViewer>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
};

export default MindMapSheet;
