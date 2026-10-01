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
import { useFetchUserInfo } from '@/hooks/use-user-setting-request';
import {
  usePublishBreadcrumbTrail,
  type BreadcrumbCrumb,
} from '@/layouts/components/breadcrumb-context';
import { Settings } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router';
import {
  ISearchAppDetailProps,
  useFetchSearchDetail,
} from '../next-searches/hooks';
import { useCheckSettings } from './hooks';
import './index.less';
import SearchHome from './search-home';
import { SearchSetting } from './search-setting';
import SearchingPage from './searching';

export default function SearchPage() {
  const [isSearching, setIsSearching] = useState(false);
  const { data: SearchData } = useFetchSearchDetail();
  const { t } = useTranslation();

  const [openSetting, setOpenSetting] = useState(false);
  const [searchText, setSearchText] = useState('');
  const location = useLocation();
  const navigate = useNavigate();
  const { data: userInfo } = useFetchUserInfo();
  const { openSetting: checkOpenSetting } = useCheckSettings(
    SearchData as ISearchAppDetailProps,
  );

  /** 搜索 > 名称. Absent while the detail is still loading, which leaves the module
   *  level alone rather than naming a search that has not arrived. */
  const breadcrumbTrail = useMemo<BreadcrumbCrumb[]>(() => {
    const name = (SearchData as ISearchAppDetailProps)?.name;

    return name ? [{ label: name }] : [];
  }, [SearchData]);

  usePublishBreadcrumbTrail(breadcrumbTrail);
  useEffect(() => {
    const initialQuery = (location.state as { searchCardQuery?: unknown } | null)
      ?.searchCardQuery;
    if (
      typeof initialQuery !== 'string' ||
      !initialQuery.trim() ||
      !SearchData
    ) {
      return;
    }

    setSearchText(initialQuery);
    if (!checkOpenSetting) {
      setIsSearching(true);
    }
    navigate(location.pathname, { replace: true, state: null });
  }, [
    SearchData,
    checkOpenSetting,
    location.pathname,
    location.state,
    navigate,
  ]);

  useEffect(() => {
    setOpenSetting(checkOpenSetting);
  }, [checkOpenSetting]);

  useEffect(() => {
    if (isSearching) {
      setOpenSetting(false);
    }
  }, [isSearching]);

  const handleToggleSettings = useCallback(() => {
    setOpenSetting((previous) => !previous);
  }, []);

  return (
    <section
      // This pane is registered under the layout group, so it is the whole
      // remaining area beneath the header: no outer margin or padding to squeeze
      // it, and the same frame-less glass surface the chat panes use instead of a
      // hard 0.5px border with the page background behind it.
      className="relative flex size-full min-w-0 flex-1"
      data-testid="search-detail"
    >
      <div className="glass-surface flex min-w-0 flex-1">
        <div className="flex-1 min-w-0 overflow-hidden">
          {!isSearching && (
            <div className="animate-fade-in h-full overflow-x-hidden overflow-y-auto">
              <SearchHome
                setIsSearching={setIsSearching}
                isSearching={isSearching}
                searchText={searchText}
                setSearchText={setSearchText}
                userInfo={userInfo}
                canSearch={!checkOpenSetting}
              />
            </div>
          )}
          {isSearching && (
            <div className="animate-fade-in h-full">
              <SearchingPage
                setIsSearching={setIsSearching}
                searchText={searchText}
                setSearchText={setSearchText}
                data={SearchData as ISearchAppDetailProps}
              />
            </div>
          )}
        </div>
      </div>

      {/* The only settings trigger: one gear in the page's own corner. The panel
          it opens is a drawer anchored to this section, so the search area keeps
          the full width and nothing is pushed to the side while it is closed. */}
      <Button
        variant="transparent"
        className="absolute right-4 top-4 z-30 bg-bg-card"
        onClick={handleToggleSettings}
        aria-label={t('search.searchSettings')}
        title={t('search.searchSettings')}
        data-testid="search-settings-open"
      >
        <Settings className="text-text-secondary" />
      </Button>

      <SearchSetting
        open={openSetting}
        setOpen={setOpenSetting}
        data={SearchData as ISearchAppDetailProps}
      />
    </section>
  );
}