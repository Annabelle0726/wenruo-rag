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
  KnowledgeRouteKey,
  KnowledgeSearchParams,
} from '@/constants/knowledge';
import { Routes } from '@/routes';
import {
  effectivePageSize,
  pageAfterResize,
  pageSizeOptionsFor,
} from '@/utils/list-capacity';
import { useCallback, useEffect, useRef } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router';
import { useListCapacity } from './use-list-capacity';

export enum SegmentIndex {
  Second = '2',
  Third = '3',
}

export const useSegmentedPathName = (index: SegmentIndex) => {
  const { pathname } = useLocation();

  const pathArray = pathname.split('/');
  return pathArray[index] || '';
};

export const useSecondPathName = () => {
  return useSegmentedPathName(SegmentIndex.Second);
};

export const useThirdPathName = () => {
  return useSegmentedPathName(SegmentIndex.Third);
};

export const useGetKnowledgeSearchParams = () => {
  const [currentQueryParameters] = useSearchParams();
  const { pathname } = useLocation();
  const isDataflowResultPage = pathname === Routes.DataflowResult;

  return {
    type: currentQueryParameters.get(KnowledgeSearchParams.Type) || '',
    documentId:
      currentQueryParameters.get(KnowledgeSearchParams.DocumentId) || '',
    knowledgeId: isDataflowResultPage
      ? currentQueryParameters.get('knowledgeId') || ''
      : currentQueryParameters.get(KnowledgeSearchParams.KnowledgeId) || '',
  };
};

export const useNavigateWithFromState = () => {
  const navigate = useNavigate();
  return useCallback(
    (path: string) => {
      navigate(path, { state: { from: path } });
    },
    [navigate],
  );
};

export const useNavigateToDataset = () => {
  const navigate = useNavigate();
  const { knowledgeId } = useGetKnowledgeSearchParams();

  return useCallback(() => {
    navigate(`/knowledge/${KnowledgeRouteKey.Dataset}?id=${knowledgeId}`);
  }, [knowledgeId, navigate]);
};

export const useGetPaginationParams = () => {
  const [currentQueryParameters] = useSearchParams();

  return {
    page: currentQueryParameters.get('page') || 1,
    size: currentQueryParameters.get('size') || 10,
  };
};

const PageSizeStorageKeyPrefix = 'RAGFlowPageSize:';

const getStoredPageSize = (pathname: string) =>
  Number(localStorage.getItem(`${PageSizeStorageKeyPrefix}${pathname}`)) ||
  null;

export const useSetPaginationParams = () => {
  const [queryParameters, setSearchParams] = useSearchParams();
  const { pathname } = useLocation();
  // What this page's list region can actually show. `null` on a page whose list
  // has no region marked (or before it is measured), in which case the user cap
  // and the application cap are all there is to go on.
  const { capacity } = useListCapacity();

  const setPaginationParams = useCallback(
    (page: number = 1, pageSize?: number) => {
      queryParameters.set('page', page.toString());
      if (pageSize) {
        queryParameters.set('size', pageSize.toString());
        // Persist the page size per main page so it survives navigation
        // to other pages, where the URL search params are dropped.
        localStorage.setItem(
          `${PageSizeStorageKeyPrefix}${pathname}`,
          pageSize.toString(),
        );
      }
      setSearchParams(queryParameters);
    },
    [setSearchParams, queryParameters, pathname],
  );

  // Moving to the page that carries the same record after a resize. This is the
  // page's own arithmetic, NOT a choice the user made, so it must never be
  // persisted: writing the derived size into `size` or into localStorage would
  // turn a measured number into a remembered preference, and a single
  // mis-measurement would then pin the list to that size on every later visit.
  //
  // `replace`, not `push`: a resize is not a navigation, and several hooks on one
  // page each derive this same page number - pushing would file one history entry
  // per caller. The equality guard makes the second caller a no-op.
  const setPageOnly = useCallback(
    (page: number) => {
      if (Number(queryParameters.get('page')) === page) return;
      queryParameters.set('page', page.toString());
      setSearchParams(queryParameters, { replace: true });
    },
    [setSearchParams, queryParameters],
  );

  // The user's own selection, from the URL or remembered for this path - a
  // MAXIMUM, never a mandate to overflow the viewport (see `effectivePageSize`).
  const userCap =
    Number(queryParameters.get('size')) || getStoredPageSize(pathname) || null;
  const size = effectivePageSize({ capacity, userCap });
  const requestedPage = Number(queryParameters.get('page')) || 1;
  const previousSizeRef = useRef<number | null>(null);

  // A resize changes how many records a page holds, so the page NUMBER that
  // carries the same offset has to change with it: page 3 of 20 is record 41,
  // which is page 4 of 12. Without this the window would jump backwards.
  const page = pageAfterResize({
    page: requestedPage,
    fromSize: previousSizeRef.current ?? size,
    toSize: size,
  });

  useEffect(() => {
    const previous = previousSizeRef.current;
    previousSizeRef.current = size;
    if (previous === null || previous === size || page === requestedPage)
      return;
    setPageOnly(page);
  }, [page, requestedPage, size, setPageOnly]);

  return {
    setPaginationParams,
    page,
    size,
    /** How many complete items this page's region shows, once measured. */
    capacity,
    /** The sizes the pager may offer here: nothing it could not honour. */
    sizeOptions: pageSizeOptionsFor(capacity),
  };
};
