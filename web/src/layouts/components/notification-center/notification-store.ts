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
  IWorkspaceNotification,
  NotificationSource,
} from '@/interfaces/notification';
import { create } from 'zustand';

/**
 * Local, in-session notification state for the navigation shell.
 *
 * It is deliberately session-only: there is no persistence layer and no
 * invented history, so closing the tab clears it. Two things it does NOT do:
 *
 * 1. it never creates an event. `syncSource` REPLACES the entries of one source
 *    with what that source currently reports, so a notification exists only
 *    while the underlying record does;
 * 2. it never fabricates a timestamp. A source that reports one keeps it, and a
 *    source that does not gets none.
 */
interface NotificationState {
  /** Source-derived entries, newest source order preserved. */
  items: IWorkspaceNotification[];
  /** Read state by notification id; the source stays the source of truth. */
  readAtById: Record<string, string>;
  syncSource: (
    source: NotificationSource,
    items: IWorkspaceNotification[],
  ) => void;
  markRead: (id: string, at: string) => void;
  markAllRead: (at: string) => void;
}

export const useNotificationStore = create<NotificationState>((set) => ({
  items: [],
  readAtById: {},
  syncSource: (source, items) =>
    set((state) => {
      // Keep the entries of every OTHER source untouched, and drop the ones this
      // source no longer reports (an answered invitation stops notifying).
      const nextItems = [
        ...state.items.filter((item) => item.source !== source),
        ...items,
      ];
      const liveIds = new Set(nextItems.map((item) => item.id));
      const readAtById = Object.fromEntries(
        Object.entries(state.readAtById).filter(([id]) => liveIds.has(id)),
      );
      return { items: nextItems, readAtById };
    }),
  markRead: (id, at) =>
    set((state) => ({ readAtById: { ...state.readAtById, [id]: at } })),
  markAllRead: (at) =>
    set((state) => ({
      readAtById: state.items.reduce<Record<string, string>>(
        (accumulator, item) => {
          accumulator[item.id] = at;
          return accumulator;
        },
        { ...state.readAtById },
      ),
    })),
}));

/** The items with read state merged in, newest entry first. */
export const selectNotifications = (
  state: NotificationState,
): IWorkspaceNotification[] =>
  state.items
    .map((item) => ({ ...item, readAt: state.readAtById[item.id] ?? null }))
    .sort((a, b) => (b.createdAt ?? '').localeCompare(a.createdAt ?? ''));

export const selectUnreadCount = (state: NotificationState): number =>
  state.items.filter((item) => !state.readAtById[item.id]).length;
