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

import { Button } from '@/components/ui/button';
import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Trash2 } from 'lucide-react';
import { useSearchHistoryStore } from './search-history-store';

interface SearchHistoryProps {
  onSelect(question: string): void;
}

/**
 * The questions this browser asked recently, as tags under the search box.
 *
 * Rendered by the caller only while the box is empty: with a question in the
 * box the reader is looking at answers, and the tags would sit between them and
 * what they just asked.
 */
export default function SearchHistory({ onSelect }: SearchHistoryProps) {
  const { t } = useTranslation();
  const entries = useSearchHistoryStore((state) => state.entries);
  const clear = useSearchHistoryStore((state) => state.clear);

  const handleSelect = useCallback(
    (question: string) => () => {
      onSelect(question);
    },
    [onSelect],
  );

  if (!entries.length) {
    return null;
  }

  return (
    <div
      className="mt-3 flex flex-wrap items-center gap-2"
      data-testid="search-history"
    >
      <span className="text-sm text-text-secondary">{t('search.history')}</span>
      {entries.map((entry) => (
        <Button
          key={entry}
          variant="transparent"
          className="bg-bg-card text-text-secondary"
          onClick={handleSelect(entry)}
          data-testid="search-history-entry"
        >
          {entry}
        </Button>
      ))}
      <Button
        variant="transparent"
        size="icon-sm"
        className="text-text-secondary"
        onClick={clear}
        aria-label={t('search.clearHistory')}
        title={t('search.clearHistory')}
        data-testid="search-history-clear"
      >
        <Trash2 className="size-3.5" />
      </Button>
    </div>
  );
}
