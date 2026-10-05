import '@testing-library/jest-dom';
import React from 'react';

// esbuild-jest compiles JSX with the classic runtime (React.createElement),
// while source files rely on the automatic runtime and never import React.
// Expose React globally so rendering components in tests works.
(globalThis as Record<string, unknown>).React = React;

// jsdom does not provide these, but react-router reads them at module scope
if (typeof globalThis.TextEncoder === 'undefined') {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { TextDecoder, TextEncoder } = require('node:util');
  Object.assign(globalThis, { TextDecoder, TextEncoder });
}

// jsdom exposes no web streams either, while eventsource-parser/stream builds a
// TransformStream at module scope and is pulled in by the chat hooks.
if (typeof globalThis.TransformStream === 'undefined') {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { TransformStream } = require('node:stream/web');
  Object.assign(globalThis, { TransformStream });
}

// Vite's import.meta.glob is rewritten to this stub by jest-esbuild-transformer.cjs
(globalThis as Record<string, unknown>).jestImportMetaGlob = () => ({});

// jsdom does not expose fetch; some modules call it at import time and
// handle the rejection themselves (e.g. utils/backend-runtime.ts)
if (typeof globalThis.fetch === 'undefined') {
  (globalThis as Record<string, unknown>).fetch = () =>
    Promise.reject(new Error('fetch is not available in tests'));
}

// jsdom exposes no ResizeObserver either, while every component that measures
// its own overflow uses one (the collapsible answer and reference bodies, the
// mind map's canvas container). A no-op observer is enough: jsdom lays nothing
// out, so there is no size to report.
if (typeof globalThis.ResizeObserver === 'undefined') {
  (globalThis as Record<string, unknown>).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// jsdom implements no `CSS.supports` (it exposes `CSS` without it), while
// src/utils/css-support.ts asks it about anchor positioning at module scope to
// decide whether the anchored dropdowns may use it. Without an answer, every
// suite that renders one of those components dies on import. "No support" is the
// truthful answer in an environment that does not lay out CSS at all.
const cssGlobal = globalThis as { CSS?: Record<string, unknown> };
if (typeof cssGlobal.CSS?.supports !== 'function') {
  cssGlobal.CSS = { ...(cssGlobal.CSS ?? {}), supports: () => false };
}

// Initialise a real i18next instance for tests. Without it react-i18next logs
// "You will need to pass in an i18next instance by using initReactI18next" on
// every render and `t()` returns the key, so a component that renders copy
// cannot be asserted on. The app's own en resource is used so tests see the
// same strings the UI does, rather than key echoes.
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import translationEn from './src/locales/en';

void i18n.use(initReactI18next).init({
  lng: 'en',
  fallbackLng: 'en',
  resources: { en: translationEn },
  interpolation: { escapeValue: false },
});
