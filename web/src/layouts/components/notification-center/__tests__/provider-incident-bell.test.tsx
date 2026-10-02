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

// Local fixture types rather than the API's: this file contains `jest.mock`, so it
// is transformed through the babel path, which cannot reference an imported binding
// in a type annotation. `team-page.test.tsx` uses the same pattern.
interface ITestIncident {
  id: string;
  provider_id: string;
  instance_id: string;
  provider_name: string;
  capability: string;
  error_class: string;
  severity: string;
  occurred_at: string | null;
  last_seen_at: string | null;
  occurrence_count: number;
  affected_operation: string;
  user_safe_message: string;
  state: string;
  resolved_at: string | null;
  resolution_kind: string | null;
}

interface ITestView {
  incidents: ITestIncident[];
  active_count: number;
  recently_resolved_count: number;
  total_in_scope: number;
  limit: number;
  offset: number;
  truncated: boolean;
  lists_incomplete: boolean;
  recently_resolved_window_days: number;
  not_answered: string[];
}

import { useNotificationStore } from '@/layouts/components/notification-center/notification-store';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import NotificationCenter from '..';

/**
 * The bell, with the two real sources it has.
 *
 * What these cases are really about: the badge counts INCIDENTS (so one incident
 * seen 30 times adds one), the two sources add up, and nothing the reader does in
 * the drawer can change an incident - the entries appear and disappear with what
 * the SERVER reports, and read state only ever moves inside the store.
 */

let mockTenants: Array<Record<string, unknown>>;
let mockProviderHealth: ITestView | undefined;
let mockRefetch: jest.Mock;

// `@/routes` builds a browser router at module scope (`createBrowserRouter`), which
// jsdom cannot construct - the repo already mocks app-shell modules for exactly this
// reason (`__mocks__/layout-recognize-form-field.js`). Only the paths this component
// navigates to are needed here.
jest.mock('@/routes', () => ({
  Routes: {
    UserSetting: '/user-setting',
    Usage: '/usage',
    ProfileTeam: '/user-setting/team',
  },
}));

jest.mock('@/hooks/use-user-setting-request', () => ({
  useListTenant: () => ({ data: mockTenants, loading: false }),
}));

jest.mock('@/hooks/use-provider-health-request', () => ({
  useFetchProviderIncidents: () => ({
    data: mockProviderHealth,
    loading: false,
    idle: false,
    error: null,
    refetch: mockRefetch,
  }),
}));

const incident = (
  overrides: Partial<ITestIncident> = {},
): ITestIncident => ({
  id: 'incident-1',
  provider_id: 'provider-1',
  instance_id: 'instance-1',
  provider_name: 'Gemini',
  capability: 'embedding',
  error_class: 'EMBEDDING_QUOTA_EXHAUSTED',
  severity: 'error',
  occurred_at: '2026-03-01 11:40:00',
  last_seen_at: '2026-03-01 11:47:00',
  occurrence_count: 3,
  affected_operation: '',
  user_safe_message: 'AI 向量化服务额度已耗尽，请更换 API Key 或等待额度重置后重试。',
  state: 'active',
  resolved_at: null,
  resolution_kind: null,
  ...overrides,
});

const view = (incidents: ITestIncident[]): ITestView => ({
  incidents,
  active_count: incidents.filter((item) => item.state === 'active').length,
  recently_resolved_count: 0,
  total_in_scope: incidents.length,
  limit: 50,
  offset: 0,
  truncated: false,
  lists_incomplete: false,
  recently_resolved_window_days: 7,
  not_answered: [],
});

const renderBell = () =>
  render(
    <MemoryRouter>
      <NotificationCenter />
    </MemoryRouter>,
  );

beforeEach(() => {
  mockTenants = [];
  mockProviderHealth = undefined;
  mockRefetch = jest.fn();
  useNotificationStore.setState({ items: [], readAtById: {} });
});

describe('the badge counts facts, not repetitions', () => {
  it('shows no badge when neither source reports anything', () => {
    renderBell();

    expect(screen.queryByTestId('notification-badge')).toBeNull();
  });

  it('counts one per active incident, whatever its occurrence count', () => {
    mockProviderHealth = view([incident({ occurrence_count: 30 })]);

    renderBell();

    expect(screen.getByTestId('notification-badge')).toHaveTextContent('1');
  });

  it('adds an invitation and an incident', () => {
    mockTenants = [
      { tenant_id: 'ws-1', name: 'Cable Team', role: 'invite', update_date: '2026-03-01 09:00:00' },
    ];
    mockProviderHealth = view([incident(), incident({ id: 'incident-2' })]);

    renderBell();

    expect(screen.getByTestId('notification-badge')).toHaveTextContent('3');
  });

  it('counts an incident once even when the server reports two capabilities of it', () => {
    mockProviderHealth = view([
      incident({ id: 'a', occurrence_count: 100 }),
      incident({ id: 'b', occurrence_count: 1 }),
    ]);

    renderBell();

    expect(screen.getByTestId('notification-badge')).toHaveTextContent('2');
  });
});

describe('an incident entry shows what a reader can act on', () => {
  it('shows the provider, the capability, the server sentence and the count', () => {
    mockProviderHealth = view([incident()]);

    renderBell();
    fireEvent.click(screen.getByTestId('notification-bell'));

    const entry = screen.getAllByTestId('notification-entry')[0];
    expect(entry).toHaveTextContent('Gemini');
    expect(entry).toHaveTextContent('Embedding');
    expect(entry).toHaveTextContent('AI 向量化服务额度已耗尽');
    expect(entry).toHaveTextContent('Occurred 3 time(s)');
  });

  it('renders no instance id, error class, key or raw provider text', () => {
    mockProviderHealth = view([
      incident({ instance_id: 'instance-MUST-NOT-APPEAR' }),
    ]);

    renderBell();
    fireEvent.click(screen.getByTestId('notification-bell'));

    const text = document.body.textContent ?? '';
    for (const forbidden of [
      'instance-MUST-NOT-APPEAR',
      'provider-1',
      'EMBEDDING_QUOTA_EXHAUSTED',
      '429',
      'api_key',
    ]) {
      expect(text).not.toContain(forbidden);
    }
  });

  it('lists no entry for a resolved incident', () => {
    mockProviderHealth = view([incident({ state: 'resolved' })]);

    renderBell();
    fireEvent.click(screen.getByTestId('notification-bell'));

    expect(screen.getByTestId('notification-empty')).toBeInTheDocument();
  });
});

describe('opening the drawer observes and never resolves', () => {
  it('refetches the read and marks the entry read, leaving the incident alone', () => {
    mockProviderHealth = view([incident()]);
    renderBell();

    fireEvent.click(screen.getByTestId('notification-bell'));

    // Opening is a READ: the same hook is asked again.
    expect(mockRefetch).toHaveBeenCalledTimes(1);
    // And the incident the server reported is still exactly what is on screen.
    expect(mockProviderHealth.incidents[0].state).toBe('active');

    const entry = screen.getAllByTestId('notification-entry')[0];
    fireEvent.click(within(entry).getByRole('button', { name: 'Mark as read' }));

    const state = useNotificationStore.getState();
    expect(Object.keys(state.readAtById)).toEqual(['provider-incident:incident-1']);
    // Read state is local UI state; the incident is untouched by it.
    expect(mockProviderHealth.incidents[0].state).toBe('active');
    expect(mockProviderHealth.incidents[0].resolution_kind).toBeNull();
  });

  it('drops the entry only when the SERVER stops reporting the incident', () => {
    mockProviderHealth = view([incident()]);
    const { rerender } = renderBell();

    expect(useNotificationStore.getState().items).toHaveLength(1);

    // The provider succeeded and the server resolved it: the source now reports
    // an empty active list, so the entry goes - the drawer did not decide it.
    mockProviderHealth = view([incident({ state: 'resolved', resolved_at: '2026-03-01 12:05:00' })]);
    rerender(
      <MemoryRouter>
        <NotificationCenter />
      </MemoryRouter>,
    );

    expect(useNotificationStore.getState().items).toEqual([]);
    expect(screen.queryByTestId('notification-badge')).toBeNull();
  });

  it('keeps the entries when a read fails', () => {
    mockProviderHealth = view([incident()]);
    renderBell();
    const before = useNotificationStore.getState().items;

    // A failed read leaves `data` as it was; it never empties the drawer.
    mockRefetch = jest.fn();
    fireEvent.click(screen.getByTestId('notification-bell'));

    expect(useNotificationStore.getState().items).toEqual(before);
  });
});
