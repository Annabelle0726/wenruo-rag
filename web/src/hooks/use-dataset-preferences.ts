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

import { useFetchUserInfo } from '@/hooks/use-user-setting-request';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

/**
 * Per-user dataset list preferences: which datasets are pinned to the top and
 * which are hidden from the list.
 *
 * These are presentation choices rather than authorization, so they live in the
 * browser instead of on the server: hiding a dataset removes it from *this*
 * user's list and changes nothing about who may read it. They are keyed by user
 * id because a shared browser must not carry one account's list layout into
 * another's.
 */
export type DatasetPreference = {
  pinned: string[];
  hidden: string[];
};

export type DatasetPreferencesState = {
  byUser: Record<string, DatasetPreference>;
  /** Whether a hidden dataset is shown greyed-in instead of omitted. */
  showHidden: boolean;
  setShowHidden: (showHidden: boolean) => void;
  togglePinned: (userId: string, datasetId: string) => void;
  toggleHidden: (userId: string, datasetId: string) => void;
};

export const EmptyDatasetPreference: DatasetPreference = {
  pinned: [],
  hidden: [],
};

/** The preferences of one user, defaulting to "nothing pinned, nothing hidden". */
export const preferencesFor = (
  byUser: Record<string, DatasetPreference>,
  userId: string,
): DatasetPreference => byUser[userId] ?? EmptyDatasetPreference;

const toggleId = (ids: string[], datasetId: string) =>
  ids.includes(datasetId)
    ? ids.filter((id) => id !== datasetId)
    : [...ids, datasetId];

export const useDatasetPreferencesStore = create<DatasetPreferencesState>()(
  persist(
    (set) => ({
      byUser: {},
      showHidden: false,
      setShowHidden: (showHidden) => set({ showHidden }),
      togglePinned: (userId, datasetId) =>
        set((state) => {
          const current = preferencesFor(state.byUser, userId);
          if (!userId) return state;
          return {
            byUser: {
              ...state.byUser,
              [userId]: {
                ...current,
                pinned: toggleId(current.pinned, datasetId),
                hidden: current.hidden.filter((id) => id !== datasetId),
              },
            },
          };
        }),
      toggleHidden: (userId, datasetId) =>
        set((state) => {
          const current = preferencesFor(state.byUser, userId);
          if (!userId) return state;
          return {
            byUser: {
              ...state.byUser,
              [userId]: {
                ...current,
                hidden: toggleId(current.hidden, datasetId),
                pinned: current.pinned.filter((id) => id !== datasetId),
              },
            },
          };
        }),
    }),
    {
      name: 'ragflow-dataset-preferences',
      version: 1,
      migrate: (persisted) => {
        const state = persisted as DatasetPreferencesState;
        return {
          ...state,
          byUser: Object.fromEntries(
            Object.entries(state.byUser ?? {}).map(([id, preference]) => [
              id,
              {
                ...preference,
                pinned: preference.pinned.filter(
                  (key) => !preference.hidden.includes(key),
                ),
              },
            ]),
          ),
        };
      },
      storage: createJSONStorage(() => localStorage),
    },
  ),
);

/**
 * The current user's dataset preferences, and the actions that change them.
 *
 * The user id comes from the session rather than a prop so a row's quick menu and
 * the list itself read the same preferences without threading it down the tree.
 */
export const useDatasetPreferences = () => {
  const { data: userInfo } = useFetchUserInfo();
  const userId = userInfo?.id ?? '';
  const byUser = useDatasetPreferencesStore((state) => state.byUser);
  const showHidden = useDatasetPreferencesStore((state) => state.showHidden);
  const setShowHidden = useDatasetPreferencesStore(
    (state) => state.setShowHidden,
  );
  const togglePinned = useDatasetPreferencesStore(
    (state) => state.togglePinned,
  );
  const toggleHidden = useDatasetPreferencesStore(
    (state) => state.toggleHidden,
  );

  const { pinned, hidden } = preferencesFor(byUser, userId);

  return {
    pinnedIds: pinned,
    hiddenIds: hidden,
    showHidden,
    setShowHidden,
    isPinned: (datasetId: string) =>
      pinned.includes(datasetId) && !hidden.includes(datasetId),
    isHidden: (datasetId: string) => hidden.includes(datasetId),
    togglePin: (datasetId: string) => togglePinned(userId, datasetId),
    toggleHide: (datasetId: string) => toggleHidden(userId, datasetId),
  };
};
