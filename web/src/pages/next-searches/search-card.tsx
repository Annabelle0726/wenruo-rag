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

import { CardIdentityIcon } from '@/components/card-identity-icon';
import { HomeCard } from '@/components/home-card';
import { MoreButton } from '@/components/more-button';
import { Routes } from '@/routes';
import { useState } from 'react';
import type { ChangeEvent, FormEvent, KeyboardEvent } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ISearchAppProps } from './hooks';
import { SearchDropdown } from './search-dropdown';

interface IProps {
  data: ISearchAppProps;
  showSearchRenameModal: (data: ISearchAppProps) => void;
}
export function SearchCard({ data, showSearchRenameModal }: IProps) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [query, setQuery] = useState('');

  const stopCardNavigation = (event: { stopPropagation: () => void }) => {
    event.stopPropagation();
  };

  const handleQueryChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    setQuery(event.target.value);
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const searchText = query.trim();
    if (!searchText) return;
    navigate(`${Routes.Search}/${data.id}`, {
      state: { searchCardQuery: searchText },
    });
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    event.stopPropagation();
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  };

  return (
    <HomeCard
      data={data}
      layout="search"
      className="relative before:pointer-events-none before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-transparent before:content-[''] hover:before:bg-cable-brand"
      leading={<CardIdentityIcon kind="search" avatar={data.avatar} />}
      trailing={
        <form
          className="relative flex h-[52px] min-w-0 w-full items-center rounded-lg border border-cable-hairline bg-bg-input/80 transition-[border-color,background-color] duration-150 focus-within:border-cable-accent/70 focus-within:bg-bg-input"
          onSubmit={handleSubmit}
          onClick={stopCardNavigation}
          onKeyDown={stopCardNavigation}
          aria-label={t('search.cardComposerLabel')}
        >
          <textarea
            rows={1}
            value={query}
            onChange={handleQueryChange}
            onKeyDown={handleKeyDown}
            onClick={stopCardNavigation}
            placeholder={t('search.cardComposerPlaceholder')}
            aria-label={t('search.cardComposerLabel')}
            className="h-full min-h-0 min-w-0 flex-1 resize-none overflow-y-auto bg-transparent px-3 py-2.5 text-xs leading-[18px] text-text-primary outline-none placeholder:text-text-secondary/80"
          />
        </form>
      }
      moreDropdown={
        <SearchDropdown
          dataset={data}
          showSearchRenameModal={showSearchRenameModal}
        >
          <MoreButton />
        </SearchDropdown>
      }
      onClick={() => navigate(`${Routes.Search}/${data.id}`)}
    />
  );
}
