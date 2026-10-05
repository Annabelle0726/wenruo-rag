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

import {
  IndentedTree,
  MIND_MAP_ZOOM_STEP,
  resetMindMapViewport,
} from '@/components/indented-tree/indented-tree';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Graph } from '@antv/g6';
import { Scan, ZoomIn, ZoomOut } from 'lucide-react';
import { useCallback, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

/** How long a toolbar zoom takes; the wheel is instant. */
const TOOLBAR_ANIMATION = { duration: 150 };

interface MindMapViewerProps {
  data: unknown;
}

/**
 * The mind map canvas and the controls that drive its viewport.
 *
 * The canvas itself takes the wheel and the drag; these buttons exist for the
 * reader who does not know that, and for the two states the gestures cannot
 * express — fitting the whole answer on screen, and getting back to 1:1.
 */
export default function MindMapViewer({ data }: MindMapViewerProps) {
  const { t } = useTranslation();
  const graphRef = useRef<Graph>();
  const [zoom, setZoom] = useState(1);

  const handleRender = useCallback((graph: Graph) => {
    graphRef.current = graph;
  }, []);

  const handleDestroy = useCallback(() => {
    graphRef.current = undefined;
  }, []);

  // A graph reports its scale after every viewport change, including the ones a
  // teardown triggers; only a finite number is worth showing.
  const handleZoomChange = useCallback((next: number) => {
    if (Number.isFinite(next)) setZoom(next);
  }, []);

  const handleZoomIn = useCallback(() => {
    graphRef.current?.zoomBy(MIND_MAP_ZOOM_STEP, TOOLBAR_ANIMATION);
  }, []);

  const handleZoomOut = useCallback(() => {
    graphRef.current?.zoomBy(1 / MIND_MAP_ZOOM_STEP, TOOLBAR_ANIMATION);
  }, []);

  const handleFitView = useCallback(() => {
    graphRef.current?.fitView({ when: 'always' }, TOOLBAR_ANIMATION);
  }, []);

  const handleResetZoom = useCallback(async () => {
    const graph = graphRef.current;
    if (!graph) return;

    await resetMindMapViewport(graph);
  }, []);

  return (
    <div
      className="relative h-full w-full overflow-hidden bg-bg-card"
      data-testid="mindmap-canvas"
    >
      <IndentedTree
        data={data}
        onRender={handleRender}
        onDestroy={handleDestroy}
        onZoomChange={handleZoomChange}
      ></IndentedTree>

      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-end p-3">
        <div
          className="pointer-events-auto flex items-center gap-1 rounded border border-border-default bg-bg-card p-1"
          data-testid="mindmap-toolbar"
        >
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={handleZoomOut}
            aria-label={t('chunk.mindZoomOut')}
            title={t('chunk.mindZoomOut')}
            data-testid="mindmap-zoom-out"
          >
            <ZoomOut className="size-4" />
          </Button>
          {/* Read-out and reset in one control: the number a reader wants to
              check is the one they click to get back to 1:1. */}
          <button
            type="button"
            onClick={handleResetZoom}
            aria-label={t('chunk.mindResetZoom')}
            title={t('chunk.mindResetZoom')}
            className="min-w-12 rounded px-1 text-center text-xs tabular-nums text-text-secondary hover:bg-surface-hover hover:text-text-primary"
            data-testid="mindmap-zoom-reset"
          >
            {Math.round(zoom * 100)}%
          </button>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={handleZoomIn}
            aria-label={t('chunk.mindZoomIn')}
            title={t('chunk.mindZoomIn')}
            data-testid="mindmap-zoom-in"
          >
            <ZoomIn className="size-4" />
          </Button>
          <Separator orientation="vertical" className="mx-1 h-4" />
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={handleFitView}
            aria-label={t('chunk.mindFitView')}
            title={t('chunk.mindFitView')}
            data-testid="mindmap-fit-view"
          >
            <Scan className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
