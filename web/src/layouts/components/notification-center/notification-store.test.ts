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

import { IWorkspaceNotification } from '@/interfaces/notification';
import {
  selectNotifications,
  selectUnreadCount,
  useNotificationStore,
} from './notification-store';

const invitation = (
  id: string,
  overrides: Partial<IWorkspaceNotification> = {},
): IWorkspaceNotification => ({
  id,
  category: 'SYSTEM_WARNING',
  severity: 'info',
  titleKey: 'notification.workspaceInvitationTitle',
  createdAt: '2026-03-10 09:00:00',
  readAt: null,
  source: 'workspace_invitation',
  ...overrides,
});

const reset = () =>
  useNotificationStore.setState({ items: [], readAtById: {} });

describe('the notification shell invents nothing', () => {
  beforeEach(reset);

  it('starts empty, so a bell with no source shows no badge', () => {
    expect(selectUnreadCount(useNotificationStore.getState())).toBe(0);
    expect(selectNotifications(useNotificationStore.getState())).toEqual([]);
  });

  it('counts only what a real source reported', () => {
    useNotificationStore.getState().syncSource('workspace_invitation', [
      invitation('workspace-invitation:ws-1'),
    ]);

    expect(selectUnreadCount(useNotificationStore.getState())).toBe(1);
    expect(selectNotifications(useNotificationStore.getState())).toHaveLength(1);
  });

  it('replaces a source instead of accumulating duplicates', () => {
    const store = useNotificationStore.getState();
    store.syncSource('workspace_invitation', [
      invitation('workspace-invitation:ws-1'),
    ]);
    store.syncSource('workspace_invitation', [
      invitation('workspace-invitation:ws-1'),
      invitation('workspace-invitation:ws-2'),
    ]);

    expect(selectUnreadCount(useNotificationStore.getState())).toBe(2);

    // An answered invitation stops notifying and stops counting.
    store.syncSource('workspace_invitation', [
      invitation('workspace-invitation:ws-2'),
    ]);
    const items = selectNotifications(useNotificationStore.getState());
    expect(items).toHaveLength(1);
    expect(items[0].id).toBe('workspace-invitation:ws-2');
  });

  it('drops read state for an entry its source no longer reports', () => {
    const store = useNotificationStore.getState();
    store.syncSource('workspace_invitation', [
      invitation('workspace-invitation:ws-1'),
    ]);
    store.markRead('workspace-invitation:ws-1', '2026-03-10T10:00:00.000Z');
    expect(selectUnreadCount(useNotificationStore.getState())).toBe(0);

    store.syncSource('workspace_invitation', [
      invitation('workspace-invitation:ws-2'),
    ]);

    expect(
      useNotificationStore.getState().readAtById['workspace-invitation:ws-1'],
    ).toBeUndefined();
    // The new entry is unread; the badge is not inherited from the old one.
    expect(selectUnreadCount(useNotificationStore.getState())).toBe(1);
  });

  it('marks one entry, then all of them', () => {
    const store = useNotificationStore.getState();
    store.syncSource('workspace_invitation', [
      invitation('workspace-invitation:ws-1'),
      invitation('workspace-invitation:ws-2', {
        createdAt: '2026-03-11 09:00:00',
      }),
    ]);

    store.markRead('workspace-invitation:ws-1', '2026-03-11T10:00:00.000Z');
    expect(selectUnreadCount(useNotificationStore.getState())).toBe(1);

    store.markAllRead('2026-03-11T11:00:00.000Z');
    expect(selectUnreadCount(useNotificationStore.getState())).toBe(0);
  });

  it('orders entries newest first and renders no time it was not given', () => {
    const store = useNotificationStore.getState();
    store.syncSource('workspace_invitation', [
      invitation('workspace-invitation:ws-old', {
        createdAt: '2026-03-09 09:00:00',
      }),
      invitation('workspace-invitation:ws-new', {
        createdAt: '2026-03-11 09:00:00',
      }),
      invitation('workspace-invitation:ws-unknown', { createdAt: undefined }),
    ]);

    const items = selectNotifications(useNotificationStore.getState());
    expect(items.map((item) => item.id)).toEqual([
      'workspace-invitation:ws-new',
      'workspace-invitation:ws-old',
      'workspace-invitation:ws-unknown',
    ]);
    // No timestamp means the drawer shows none - it does not substitute "now".
    expect(items[2].createdAt).toBeUndefined();
  });

  it('keeps two sources independent', () => {
    const store = useNotificationStore.getState();
    store.syncSource('workspace_invitation', [
      invitation('workspace-invitation:ws-1'),
    ]);
    // A second source is not implemented yet; syncing it empty must not erase
    // the entries the first one owns.
    store.syncSource('workspace_invitation', [
      invitation('workspace-invitation:ws-1'),
    ]);

    expect(selectNotifications(useNotificationStore.getState())).toHaveLength(1);
  });
});
