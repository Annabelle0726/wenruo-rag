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

import { render, screen, within } from '@testing-library/react';
import i18n from 'i18next';
import translationZh from '@/locales/zh';
import ProviderHealth from '../provider-health';

/**
 * The five states, and the two that must never be confused: an EMPTY answer and a
 * FAILED read. The third one a reader must never be shown is a green light, so
 * several of these cases assert what is ABSENT as much as what is present.
 */

let mockState: {
  data?: ITestView;
  loading: boolean;
  idle: boolean;
  error: { kind: string } | null;
  refetch: jest.Mock;
};

jest.mock('@/hooks/use-provider-health-request', () => ({
  ProviderHealthErrorKind: { Refused: 'refused', Unavailable: 'unavailable' },
  useFetchProviderIncidents: () => mockState,
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

const setState = (next: Partial<typeof mockState>) => {
  mockState = {
    data: undefined,
    loading: false,
    idle: false,
    error: null,
    refetch: jest.fn(),
    ...next,
  };
};

const renderPage = () => render(<ProviderHealth />);

beforeEach(() => setState({ loading: true }));
afterEach(() => {
  void i18n.changeLanguage('en');
});

describe('the idle state claims nothing', () => {
  it('says the workspace is being resolved rather than showing an empty result', () => {
    setState({ idle: true, loading: false });

    renderPage();

    expect(screen.getByTestId('provider-health-idle')).toBeInTheDocument();
    expect(screen.queryByTestId('provider-health-empty')).toBeNull();
    expect(screen.queryByTestId('provider-health-ready')).toBeNull();
  });
});

describe('the loading state is a skeleton, not a claim', () => {
  it('renders a loading placeholder while the read is in flight', () => {
    setState({ loading: true });

    renderPage();

    expect(screen.getByTestId('provider-health-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('provider-health-empty')).toBeNull();
    expect(screen.queryByTestId('provider-health-error')).toBeNull();
  });
});

describe('an empty answer is reported as an absence of FACTS', () => {
  it('shows the honest empty state and no health verdict', () => {
    setState({ data: view([]), loading: false });

    const { container } = renderPage();

    const empty = screen.getByTestId('provider-health-empty');
    expect(empty).toHaveTextContent('No provider health fact is recorded yet');
    expect(empty).toHaveTextContent(
      'Once a provider call fails in a way this platform can classify',
    );
    // The copy DENIES a health claim rather than making one, and nothing on the
    // page carries a status token: no tag, and no success colour anywhere.
    expect(empty).toHaveTextContent('an empty list never means the provider is healthy');
    expect(container.querySelectorAll('.settings-tag')).toHaveLength(0);
    expect(container.innerHTML).not.toContain('state-success');
    expect(screen.queryByTestId('provider-health-error')).toBeNull();
  });
});

describe('a failed read is never rendered as an empty answer', () => {
  it('shows the error state with a retry, and no empty panel', () => {
    const refetch = jest.fn();
    setState({
      error: { kind: 'unavailable' },
      loading: false,
      refetch,
    });

    renderPage();

    const error = screen.getByTestId('provider-health-error');
    expect(error).toHaveTextContent('Provider health could not be read');
    expect(error).toHaveTextContent('This is a failed read, not an empty result.');
    expect(screen.queryByTestId('provider-health-empty')).toBeNull();

    within(error).getByRole('button', { name: 'Retry' }).click();
    expect(refetch).toHaveBeenCalled();
  });

  it('reports a refusal as a refusal, with no retry that cannot succeed', () => {
    setState({ error: { kind: 'refused' }, loading: false });

    renderPage();

    const error = screen.getByTestId('provider-health-error');
    expect(error).toHaveTextContent('You cannot read provider health here');
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull();
    expect(screen.queryByTestId('provider-health-empty')).toBeNull();
  });
});

describe('an active incident renders the facts a reader can act on', () => {
  it('shows provider, capability, severity, state, message and history', () => {
    setState({ data: view([incident()]), loading: false });

    renderPage();

    const row = screen.getByTestId('provider-incident');
    expect(row).toHaveAttribute('data-state', 'active');
    // Provider · capability, in the row's identity line.
    expect(row).toHaveTextContent('Gemini');
    expect(row).toHaveTextContent('Embedding');
    expect(within(row).getByTestId('provider-incident-severity')).toHaveTextContent(
      'Error',
    );
    expect(within(row).getByTestId('provider-incident-state')).toHaveTextContent(
      'In progress',
    );
    // The server's own sentence, not a client-side class name.
    expect(within(row).getByTestId('provider-incident-message')).toHaveTextContent(
      'AI 向量化服务额度已耗尽',
    );
    expect(within(row).getByTestId('provider-incident-history')).toHaveTextContent(
      'Occurred 3 time(s)',
    );
    expect(within(row).getByTestId('provider-incident-history')).toHaveTextContent(
      '2026-03-01 11:47',
    );
  });

  it('never renders the internal ids, the error class or a raw body', () => {
    setState({
      data: view([
        incident({
          instance_id: 'instance-MUST-NOT-APPEAR',
          provider_id: 'provider-MUST-NOT-APPEAR',
        }),
      ]),
      loading: false,
    });

    renderPage();

    const text = document.body.textContent ?? '';
    for (const forbidden of [
      'instance-MUST-NOT-APPEAR',
      'provider-MUST-NOT-APPEAR',
      'EMBEDDING_QUOTA_EXHAUSTED',
      '429',
      'RESOURCE_EXHAUSTED',
    ]) {
      expect(text).not.toContain(forbidden);
    }
  });
});

describe('a resolved incident is distinguishable without turning green', () => {
  it('states when it was resolved and is not shown as active', () => {
    setState({
      data: view([
        incident({
          state: 'resolved',
          resolved_at: '2026-03-01 12:05:00',
          severity: 'warning',
        }),
      ]),
      loading: false,
    });

    const { container } = renderPage();

    const row = screen.getByTestId('provider-incident');
    expect(row).toHaveAttribute('data-state', 'resolved');
    expect(within(row).getByTestId('provider-incident-state')).toHaveTextContent(
      'Recovered',
    );
    expect(
      within(row).getByTestId('provider-incident-resolved-at'),
    ).toHaveTextContent('Recovered at 2026-03-01 12:05');
    expect(screen.getByTestId('provider-incidents-resolved')).toBeInTheDocument();
    expect(screen.queryByTestId('provider-incidents-active')).toBeNull();
    // "Recovered" describes the incident. The page paints no success colour, so
    // it cannot read as "this provider is healthy".
    expect(container.innerHTML).not.toContain('state-success');
    const tags = Array.from(container.querySelectorAll('.settings-tag')).map(
      (element) => element.textContent ?? '',
    );
    for (const verdict of ['Healthy', 'Degraded', 'Unavailable', 'Operational']) {
      expect(tags.join(' ')).not.toContain(verdict);
    }
  });
});

describe('capabilities and providers are not a closed set', () => {
  it('labels chat and embedding from the same vocabulary', () => {
    setState({
      data: view([
        incident({ id: 'a', capability: 'chat', provider_name: 'DeepSeek' }),
        incident({ id: 'b', capability: 'embedding' }),
      ]),
      loading: false,
    });

    renderPage();

    const rows = screen.getAllByTestId('provider-incident');
    expect(rows[0]).toHaveTextContent('DeepSeek');
    expect(rows[0]).toHaveTextContent('Chat');
    expect(rows[1]).toHaveTextContent('Gemini');
    expect(rows[1]).toHaveTextContent('Embedding');
  });

  it('renders an unknown provider and capability by their own names', () => {
    setState({
      data: view([
        incident({
          capability: 'transcribe',
          provider_name: 'SomeFutureProvider',
        }),
      ]),
      loading: false,
    });

    renderPage();

    const row = screen.getByTestId('provider-incident');
    expect(row).toHaveTextContent('SomeFutureProvider');
    expect(row).toHaveTextContent('transcribe');
    // No key echo and no humanised guess.
    expect(row.textContent).not.toContain('providerCapability');
  });
});

describe('the copy is translated in both supported languages', () => {
  it('renders the Chinese labels when the language is Chinese', async () => {
    i18n.addResourceBundle('zh', 'translation', translationZh.translation);
    await i18n.changeLanguage('zh');
    setState({
      data: view([incident({ capability: 'chat', state: 'active' })]),
      loading: false,
    });

    renderPage();

    const row = screen.getByTestId('provider-incident');
    expect(row).toHaveTextContent('对话');
    expect(row).toHaveTextContent('处理中');
    expect(within(row).getByTestId('provider-incident-history')).toHaveTextContent(
      '发生 3 次',
    );
  });

  it('renders the Chinese empty state as an absence of facts', async () => {
    i18n.addResourceBundle('zh', 'translation', translationZh.translation);
    await i18n.changeLanguage('zh');
    setState({ data: view([]), loading: false });

    renderPage();

    expect(screen.getByTestId('provider-health-empty')).toHaveTextContent(
      '尚未记录任何供应商健康事实',
    );
    expect(screen.getByTestId('provider-health-empty')).toHaveTextContent(
      '供应商调用发生可识别故障后',
    );
  });
});

describe('the surface uses theme tokens, so both themes hold', () => {
  it('paints no literal colour and no inline colour style', () => {
    setState({
      data: view([incident(), incident({ id: 'w', severity: 'warning' })]),
      loading: false,
    });

    const { container } = renderPage();
    const markup = container.innerHTML;

    // A hex colour or an inline colour declaration would be a value that cannot
    // follow the theme; the severity tags must use the state tokens instead.
    expect(markup).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(markup).not.toMatch(/style="[^"]*color:/);
    expect(markup).toContain('text-state-error');
    expect(markup).toContain('text-state-warning');
    expect(markup).toContain('settings-tile');
  });
});
