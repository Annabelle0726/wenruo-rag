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

import { create } from 'zustand';

/**
 * Recently asked questions, newest first.
 *
 * Kept in the browser only: a search history is one operator's own trail, and
 * writing it to the server would make every keystroke-free search a write for a
 * list nobody else reads. The list survives a reload, which is the whole point
 * of it, and it is capped at the number the search box shows.
 */
const StorageKey = 'ragflow-search-history';
const MaxEntries = 5;

const readHistory = (): string[] => {
  try {
    const stored = localStorage.getItem(StorageKey);
    const parsed = stored ? JSON.parse(stored) : [];

    return Array.isArray(parsed)
      ? parsed
          .filter((entry): entry is string => typeof entry === 'string')
          .slice(0, MaxEntries)
      : [];
  } catch {
    // A private-mode or corrupted value must not stop the page from rendering.
    return [];
  }
};

const writeHistory = (entries: string[]) => {
  try {
    localStorage.setItem(StorageKey, JSON.stringify(entries));
  } catch {
    // Quota or a blocked storage: the in-memory list still works for this visit.
  }
};

interface SearchHistoryState {
  entries: string[];
  remember(question: string): void;
  clear(): void;
}

export const useSearchHistoryStore = create<SearchHistoryState>((set, get) => ({
  entries: readHistory(),
  remember: (question) => {
    const trimmed = question.trim();
    if (!trimmed) {
      return;
    }

    // Re-asking a question moves it back to the front rather than duplicating it.
    const entries = [
      trimmed,
      ...get().entries.filter((entry) => entry !== trimmed),
    ].slice(0, MaxEntries);
    writeHistory(entries);
    set({ entries });
  },
  clear: () => {
    writeHistory([]);
    set({ entries: [] });
  },
}));
