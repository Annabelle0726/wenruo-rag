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

import { Graph as G6Graph, GraphEvent, treeToGraphData } from '@antv/g6';
import { useSize } from 'ahooks';
import { useEffect, useRef } from 'react';

/**
 * The indented tree a question's mind map is drawn as.
 *
 * The map used to be fitted to its container on every render, so a rich answer
 * — which is the normal case — scaled the whole tree down until the labels were
 * unreadable, and there was no way back: the nodes were 0.1px hit targets, so
 * the collapse behaviour had nothing to click. Three things fix that here:
 *
 * - a fresh map opens at 1:1 and is panned by the reader, not scaled to fit;
 * - each node is a chip the size of its own label, which makes it both legible
 *   and clickable;
 * - the tree opens with a few levels expanded and the rest collapsed, so a
 *   wide answer does not start as a wall of text.
 */

/** Canvas padding around the tree, so the root does not sit on the edge. */
const VIEW_PADDING = 24;
/**
 * Levels shown when the map opens, counting the root as level 0. The rest of
 * the tree is one click away on the node that owns it.
 */
const VISIBLE_LEVELS = 3;
/** The scale a fresh map opens at: real size, never shrunk to fit. */
const DEFAULT_ZOOM = 1;
/**
 * Bounds the wheel and the toolbar share. Without a floor the wheel can shrink
 * the tree into a speck, which is the state the old view opened in.
 */
export const MIND_MAP_ZOOM_RANGE: [number, number] = [0.2, 3];
/** One toolbar click, and close to what one wheel notch does. */
export const MIND_MAP_ZOOM_STEP = 1.25;

const LABEL_FONT_SIZE = 12;
const NODE_MAX_WIDTH = 360;
const NODE_MIN_WIDTH = 52;
const NODE_VERTICAL_PADDING = 10;
const NODE_LINE_HEIGHT = LABEL_FONT_SIZE + 6;
/** Roughly the share of an em a monospace-ish glyph takes. */
const LATIN_GLYPH_RATIO = 0.55;
/** A full-width glyph: CJK, kana, and the full-width forms that follow them. */
const FULL_WIDTH_GLYPH = /[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef]/;

export interface IndentedTreeProps {
  /** Rendered by the G6 graph. */
  onRender?: (graph: G6Graph) => void;
  onDestroy?: () => void;
  /** Reported after every viewport change, so a toolbar can show the scale. */
  onZoomChange?: (zoom: number) => void;
  data: unknown;
}

/** The tree as it arrives: a node, its heading, and its subtree. */
interface MindMapNode {
  id?: string;
  children?: MindMapNode[];
  style?: Record<string, unknown>;
}

/**
 * The part of a node the drawing reads. Both the mind map's own tree and G6's
 * node datum satisfy it — the latter is what the style and layout callbacks
 * hand back, after the tree has been through `treeToGraphData`.
 */
interface NodeLike {
  id?: unknown;
  depth?: unknown;
  children?: unknown;
  style?: unknown;
}

const hasChildren = (node: NodeLike) =>
  Array.isArray(node.children) && node.children.length > 0;

const isCollapsed = (node: NodeLike) =>
  Boolean((node.style as { collapsed?: boolean } | undefined)?.collapsed);

/**
 * Ids are what G6 keys nodes by, and the mind map's own ids are the headings it
 * drew the tree from — so a node without one is named after its position.
 */
const assignIds = (node: MindMapNode, parentId = '', index = 0): void => {
  if (!node.id) node.id = parentId ? `${parentId}-${index}` : 'root';
  node.children?.forEach((child, idx) => assignIds(child, node.id, idx));
};

/**
 * Marks every subtree below `visibleLevels` collapsed, so the map opens as an
 * outline instead of the whole answer at once. A leaf is never marked: it owns
 * no subtree, and the marker would promise a disclosure that does not exist.
 */
const collapseBelow = (node: MindMapNode, level: number, visibleLevels: number) => {
  node.style = {
    ...node.style,
    collapsed: Boolean(node.children?.length) && level >= visibleLevels,
  };
  node.children?.forEach((child) => collapseBelow(child, level + 1, visibleLevels));
};

const cloneTree = (tree: unknown): MindMapNode =>
  JSON.parse(JSON.stringify(tree ?? {})) as MindMapNode;

/** The text a node draws; the marker only appears on nodes that own a subtree. */
const labelOf = (node: NodeLike) => {
  const text = String(node.id ?? '');
  if (!hasChildren(node)) return text;
  return `${isCollapsed(node) ? '▸' : '▾'} ${text}`;
};

const textWidth = (text: string) =>
  Array.from(text).reduce(
    (width, glyph) =>
      width +
      (FULL_WIDTH_GLYPH.test(glyph)
        ? LABEL_FONT_SIZE
        : LABEL_FONT_SIZE * LATIN_GLYPH_RATIO),
    0,
  );

/**
 * The node's own box, measured from the text it draws.
 *
 * The layout spaces nodes by these numbers and the chip is drawn at this size,
 * so text measured short would put a node on top of its neighbour. Chinese runs
 * about twice as wide as the 6px-per-character estimate this used to carry.
 */
const getNodeSize = (node: NodeLike): [number, number] => {
  const text = labelOf(node);
  const width = Math.min(
    Math.max(textWidth(text) + LABEL_FONT_SIZE + 8, NODE_MIN_WIDTH),
    NODE_MAX_WIDTH,
  );
  const lines = Math.max(1, Math.ceil(textWidth(text) / (width - 12)));
  return [width, lines * NODE_LINE_HEIGHT + NODE_VERTICAL_PADDING];
};

/**
 * Whether a graph can still be driven.
 *
 * React runs every effect twice in development, so the graph a render was
 * started for is destroyed before its own `render()` promise settles. Touching
 * it then logs a G6 error and walks a torn-down viewport.
 */
const isAlive = (graph: G6Graph | undefined): graph is G6Graph =>
  Boolean(graph && !graph.destroyed);

/**
 * Puts the root back at the top-left of the canvas at 1:1.
 *
 * The reader's own scale is left alone by every other path — a resize, a new
 * question and a collapse all keep whatever viewport they were looking at; only
 * the toolbar's reset and the first render call this.
 */
export const resetMindMapViewport = async (graph: G6Graph) => {
  if (!isAlive(graph)) return;

  await graph.zoomTo(DEFAULT_ZOOM);

  // `treeToGraphData` stamps the depth on every node, so the root is the node
  // level with the canvas origin whatever the map calls it.
  const nodes = graph.getNodeData() as NodeLike[];
  const root = nodes.find((node) => Number(node.depth) === 0) ?? nodes[0];
  const bounds = root?.id
    ? graph.getElementRenderBounds(String(root.id))
    : undefined;
  if (!bounds) {
    await graph.translateTo([VIEW_PADDING, VIEW_PADDING]);
    return;
  }

  await graph.translateTo([
    VIEW_PADDING - bounds.min[0],
    VIEW_PADDING - bounds.min[1],
  ]);
};

/** Reads the design tokens the canvas draws with, so both themes stay correct. */
const readCanvasTokens = (container: HTMLElement) => {
  const styles = window.getComputedStyle(container);
  const token = (name: string) => styles.getPropertyValue(name).trim();
  const rgb = (name: string) => {
    const value = token(name);
    return value ? `rgb(${value})` : undefined;
  };

  return {
    textPrimary: rgb('--text-primary') ?? '#303133',
    surface: token('--bg-base') || '#f0f2f5',
    border: token('--border-default') || '#dcdfe6',
  };
};

export const IndentedTree = ({
  onRender,
  onDestroy,
  onZoomChange,
  data,
}: IndentedTreeProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<G6Graph>();
  // Kept in refs so a parent re-render with a fresh callback identity cannot
  // rebuild the graph — the viewport a reader has panned to is not theirs to
  // reset.
  const callbacksRef = useRef({ onRender, onDestroy, onZoomChange });
  callbacksRef.current = { onRender, onDestroy, onZoomChange };

  const size = useSize(containerRef);
  const width = size?.width;
  const height = size?.height;

  useEffect(() => {
    const graph = new G6Graph({ container: containerRef.current! });
    graphRef.current = graph;
    // Set before `destroy()` and read by the handler below: `graph.destroyed` is
    // only marked once that teardown has run to the end.
    let alive = true;

    const reportZoom = () => {
      if (!alive || !isAlive(graph)) return;
      try {
        callbacksRef.current.onZoomChange?.(graph.getZoom());
      } catch {
        // G6 emits a last transform while a teardown is in flight, after the
        // viewport it would read has been released and before the graph marks
        // itself destroyed. There is no scale to report in that window, and
        // nothing for the caller to do about it.
      }
    };
    graph.on(GraphEvent.AFTER_TRANSFORM, reportZoom);

    return () => {
      alive = false;
      graph.off(GraphEvent.AFTER_TRANSFORM, reportZoom);
      graph.destroy();
      callbacksRef.current.onDestroy?.();
      graphRef.current = undefined;
    };
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    const graph = graphRef.current;

    if (!container || !isAlive(graph) || !data) return;

    const tokens = readCanvasTokens(container);
    const tree = cloneTree(data);
    assignIds(tree);
    collapseBelow(tree, 0, VISIBLE_LEVELS);

    graph.setOptions({
      // No `autoFit`: a map that fits itself is a map that shrinks its own text
      // as the answer grows. The toolbar offers fitting as an explicit choice.
      zoomRange: MIND_MAP_ZOOM_RANGE,
      node: {
        type: 'rect',
        style: (datum: NodeLike) => {
          const [width, height] = getNodeSize(datum);
          return {
            size: [width, height],
            radius: 2,
            fill: tokens.surface,
            stroke: tokens.border,
            lineWidth: 1,
            cursor: 'pointer',
            labelText: labelOf(datum),
            labelPlacement: 'center',
            labelFill: tokens.textPrimary,
            labelFontSize: LABEL_FONT_SIZE,
            // A long heading wraps inside its chip rather than running past the
            // box the layout reserved for it.
            labelWordWrap: true,
            labelMaxWidth: width - 12,
          };
        },
        animation: {
          enter: false,
        },
      },
      edge: {
        type: 'polyline',
        style: {
          radius: 4,
          stroke: tokens.border,
          router: {
            type: 'orth',
          },
        },
        animation: {
          enter: false,
        },
      },
      layout: {
        type: 'indented',
        direction: 'LR',
        indent: 48,
        getHeight: (datum: NodeLike) => getNodeSize(datum)[1],
        getWidth: (datum: NodeLike) => getNodeSize(datum)[0],
        getVGap: () => 10,
      },
      behaviors: [
        // G6 only pans when the drag starts on bare canvas, which leaves a map
        // that fills its panel impossible to move: every drag lands on a node.
        { type: 'drag-canvas', key: 'drag-canvas', enable: true, range: Infinity },
        // G6 zooms around the pointer, which is the behaviour a reader expects
        // from a map: the place under the cursor stays under the cursor.
        { type: 'zoom-canvas', key: 'zoom-canvas', sensitivity: 1 },
        // Single click, not the G6 default of double click: the node is the only
        // thing in the map to click, so there is nothing to disambiguate from.
        {
          type: 'collapse-expand',
          key: 'collapse-expand',
          trigger: 'click',
          animation: false,
          align: true,
        },
      ],
    });

    graph.setData(treeToGraphData(tree as never));

    graph
      .render()
      .then(() => resetMindMapViewport(graph))
      .then(() => {
        if (!isAlive(graph)) return;
        callbacksRef.current.onRender?.(graph);
        callbacksRef.current.onZoomChange?.(graph.getZoom());
      })
      .catch((error) => console.debug(error));
  }, [data]);

  // G6 sizes its canvas at creation time, so it has to be told when the
  // container changes. The viewport is left where the reader put it: resizing a
  // panel must not throw away the part of the map they were reading.
  useEffect(() => {
    const graph = graphRef.current;

    if (!isAlive(graph) || !width || !height) return;

    const [canvasWidth, canvasHeight] = graph.getSize();
    if (canvasWidth === width && canvasHeight === height) return;

    graph.resize(width, height);
  }, [width, height]);

  return <div ref={containerRef} style={{ width: '100%', height: '100%' }} />;
};
