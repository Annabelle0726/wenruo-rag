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
interface ITestAccounting {
  attempted_calls: number;
  settled_attempts: number;
  reserved_attempts: number;
  unsettled_attempts: number;
  outstanding_attempts: number;
  unrecognised_status_attempts: number;
  settled_tokens: number;
  outstanding_reserved_tokens: number;
  effective_tokens: number;
  settled_estimated_cost_micros: number | null;
  outstanding_reserved_cost_micros: number | null;
  cost_coverage: 'complete' | 'partial' | 'unavailable';
  settled_cost_coverage: 'complete' | 'partial' | 'unavailable';
  outstanding_cost_coverage: 'complete' | 'partial' | 'unavailable';
  cost_established_rows: number;
  cost_unestablished_rows: number;
  zero_usage_rows: number;
}

interface ITestMemberRow {
  user_id: string;
  nickname: string | null;
  name_available: boolean;
  live_member: boolean;
  role: string | null;
  accounting: ITestAccounting;
}

interface ITestBucket {
  period: string;
  attempted_calls: number;
  accounting: ITestAccounting;
}

interface ITestReportPayload {
  view: string;
  scope: Record<string, unknown>;
  period: Record<string, unknown>;
  accounting: ITestAccounting;
  cost: Record<string, unknown>;
  notes: string[];
  reconciliation?: Record<string, unknown>;
  data?: Record<string, unknown>;
}

import { fireEvent, render, screen, within } from '@testing-library/react';
import i18n from 'i18next';
import translationZh from '@/locales/zh';
import { MemberUsageReport } from '../components/member-usage-report';

const mockReport = jest.fn();

jest.mock('@/hooks/use-workspace-usage-request', () => ({
  useFetchMemberReport: (...args: unknown[]) => mockReport(...args),
}));

const accounting = (
  overrides: Partial<ITestAccounting> = {},
): ITestAccounting => ({
  attempted_calls: 3,
  settled_attempts: 1,
  reserved_attempts: 2,
  unsettled_attempts: 0,
  outstanding_attempts: 2,
  unrecognised_status_attempts: 0,
  settled_tokens: 150,
  outstanding_reserved_tokens: 800,
  effective_tokens: 950,
  settled_estimated_cost_micros: 700,
  outstanding_reserved_cost_micros: null,
  cost_coverage: 'partial',
  settled_cost_coverage: 'complete',
  outstanding_cost_coverage: 'unavailable',
  cost_established_rows: 1,
  cost_unestablished_rows: 2,
  zero_usage_rows: 0,
  ...overrides,
});

const memberRow = (
  overrides: Partial<ITestMemberRow> = {},
): ITestMemberRow => ({
  user_id: 'member-a-0123456789',
  nickname: 'Member A',
  name_available: true,
  live_member: true,
  role: 'normal',
  accounting: accounting(),
  ...overrides,
});

const buckets = (count: number, periodOf: (index: number) => string): ITestBucket[] =>
  Array.from({ length: count }, (_, index) => ({
    period: periodOf(index),
    attempted_calls: index + 1,
    accounting: accounting({ attempted_calls: index + 1 }),
  }));

const dayPeriod = (index: number) => `2026-03-${String(index + 1).padStart(2, '0')}`;

const payload = (
  overrides: Partial<ITestReportPayload> = {},
): ITestReportPayload => ({
  view: 'member_report',
  scope: { subject_user_id: 'member-a-0123456789' },
  period: { kind: 'day', start_day: '2026-03-01', end_day: '2026-03-31', days: 31 },
  accounting: accounting(),
  cost: { term: 'Estimated model cost', unit: 'micro_usd', coverage: 'partial' },
  notes: [],
  reconciliation: {
    ledger_attempted_calls: 3,
    counter_calls: 3,
    calls_consistent: true,
    ledger_effective_tokens: 950,
    counter_tokens: 950,
    tokens_consistent: true,
    counter_rows: 1,
    semantics: 'counters are budget occupancy',
  },
  data: {
    member: {
      user_id: 'member-a-0123456789',
      nickname: 'Member A',
      name_available: true,
      live_member: true,
      role: 'normal',
    },
    daily: { buckets: buckets(10, dayPeriod), granularity: 'day', zero_filled: 'server text' },
    monthly: {
      buckets: [{ period: '2026-03', attempted_calls: 9, accounting: accounting() }],
      granularity: 'month',
      zero_filled: 'server text',
    },
    models: {
      models: [
        {
          recorded_model_name: 'chat-x',
          bucket: 'chat-x',
          attribution: 'recorded_model_name_only',
          provider: null,
          key_instance: null,
          workload: null,
          accounting: accounting(),
        },
      ],
      total_buckets: 1,
      limit: 50,
      offset: 0,
      truncated: false,
      not_answered: 'provider is null by design',
    },
    not_answered: 'these are the figures the member breakdown publishes',
  },
  ...overrides,
});

const ready = (overrides: Partial<ITestReportPayload> = {}) =>
  mockReport.mockReturnValue({
    data: payload(overrides),
    loading: false,
    error: null,
    refetch: jest.fn(),
  });

const renderReport = (member = memberRow()) =>
  render(
    <MemberUsageReport
      member={member}
      window={{ start_day: '2026-03-01', end_day: '2026-03-31' }}
    />,
  );

const dayRowsRendered = () =>
  Array.from({ length: 10 }, (_, index) => dayPeriod(index)).filter(
    (period) => screen.queryByText(period) !== null,
  );

beforeEach(() => {
  mockReport.mockReset();
  void i18n.changeLanguage('en');
});

describe('the four states, and the two that must never be confused', () => {
  it('renders the caller identity while the read is in flight', () => {
    mockReport.mockReturnValue({ loading: true, error: null, refetch: jest.fn() });

    renderReport();

    expect(screen.getByTestId('member-report-loading')).toBeInTheDocument();
    expect(screen.getByTestId('member-report-identity')).toHaveTextContent('Member A');
    expect(screen.queryByTestId('member-report-ready')).not.toBeInTheDocument();
  });

  it('reports a failed read as a failure, never as an absence of usage', () => {
    mockReport.mockReturnValue({
      loading: false,
      error: new Error('refused'),
      refetch: jest.fn(),
    });

    renderReport();

    const failed = screen.getByTestId('member-report-failed');
    expect(within(failed).getByTestId('member-report-unavailable')).toBeInTheDocument();
    // The honest empty state and the failure are different answers.
    expect(screen.queryByTestId('member-report-empty')).not.toBeInTheDocument();
    expect(screen.queryByTestId('member-report-ready')).not.toBeInTheDocument();
    expect(within(failed).getByRole('button')).toBeInTheDocument();
  });

  it('says a member recorded nothing instead of drawing a report of zeros', () => {
    ready({
      accounting: accounting({
        attempted_calls: 0,
        settled_tokens: 0,
        outstanding_reserved_tokens: 0,
        effective_tokens: 0,
        settled_estimated_cost_micros: null,
        settled_cost_coverage: 'unavailable',
      }),
    });

    renderReport();

    expect(screen.getByTestId('member-report-empty')).toBeInTheDocument();
    expect(screen.getByTestId('member-report-no-rows')).toBeInTheDocument();
    // No totals grid and no cost tile: zero attempts is an absence of records.
    expect(screen.queryByTestId('member-report-ready')).not.toBeInTheDocument();
    expect(screen.queryByTestId('member-report-settled-cost')).not.toBeInTheDocument();
  });

  it('renders the report when the read answered', () => {
    ready();

    renderReport();

    const report = screen.getByTestId('member-report-ready');
    expect(within(report).getByTestId('member-report-identity')).toHaveTextContent('Member A');
    expect(within(report).getByTestId('member-report-settled-cost')).toBeInTheDocument();
    expect(within(report).getByTestId('member-report-outstanding-cost')).toBeInTheDocument();
    expect(within(report).getByTestId('member-report-reconciliation')).toBeInTheDocument();
  });
});

describe('the identity block', () => {
  it('labels a removed member and keeps a stable id on screen', () => {
    ready({
      data: {
        ...payload().data,
        member: {
          user_id: 'member-a-0123456789',
          nickname: 'Member A',
          name_available: true,
          live_member: false,
          role: null,
        },
      },
    });

    renderReport(memberRow({ live_member: false, role: null }));

    expect(screen.getByText('No longer a member')).toBeInTheDocument();
    expect(screen.getByTestId('member-report-id')).toHaveTextContent('member-a');
  });

  it('falls back to the row while the read has not answered', () => {
    mockReport.mockReturnValue({ loading: true, error: null, refetch: jest.fn() });

    renderReport(memberRow({ nickname: null, user_id: 'owner-user-id' }));

    expect(screen.getByTestId('member-report-identity')).toHaveTextContent('owner-user-id');
  });
});

describe('the daily table previews the latest seven days', () => {
  it('shows seven days, expands to the whole window and collapses back', () => {
    ready();

    renderReport();

    expect(dayRowsRendered()).toHaveLength(7);
    // The LATEST seven, so the first day of the window is not among them yet.
    expect(screen.queryByText('2026-03-01')).not.toBeInTheDocument();
    expect(screen.getByText('2026-03-10')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /View all dates/ }));

    expect(dayRowsRendered()).toHaveLength(10);
    expect(screen.getByText('2026-03-01')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Show only the latest/ }));

    expect(dayRowsRendered()).toHaveLength(7);
    expect(screen.queryByText('2026-03-01')).not.toBeInTheDocument();
  });

  it('offers no expand control when the window already fits the preview', () => {
    ready({
      data: {
        ...payload().data,
        daily: { buckets: buckets(7, dayPeriod), granularity: 'day', zero_filled: 'server text' },
      },
    });

    renderReport();

    expect(dayRowsRendered()).toHaveLength(7);
    expect(screen.queryByRole('button', { name: /View all dates/ })).not.toBeInTheDocument();
  });
});

describe('the monthly table is an accordion, closed by default', () => {
  it('renders no month row until it is opened, and hides it again on collapse', () => {
    ready();

    renderReport();

    expect(screen.queryByText('2026-03')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Monthly usage' }));
    expect(screen.getByText('2026-03')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Monthly usage' }));
    expect(screen.queryByText('2026-03')).not.toBeInTheDocument();
  });
});

describe('the report reads the server, and asks for the page window', () => {
  it('forwards the member and the current window to the read', () => {
    ready();

    renderReport();

    expect(mockReport).toHaveBeenCalledWith('member-a-0123456789', {
      start_day: '2026-03-01',
      end_day: '2026-03-31',
    });
  });

  it('shows the recorded-model breakdown the server returned', () => {
    ready();

    renderReport();

    expect(screen.getByText('chat-x')).toBeInTheDocument();
    expect(screen.getByText('Recorded model breakdown')).toBeInTheDocument();
  });

  it('never renders the server zero_filled sentence as the daily hint', () => {
    ready();

    renderReport();

    expect(screen.queryByText('server text')).not.toBeInTheDocument();
    expect(screen.getByText(/Shows the latest 7 days first/)).toBeInTheDocument();
  });
});

describe('the copy is translated', () => {
  it('renders the Chinese labels and the requested Chinese hint', async () => {
    i18n.addResourceBundle('zh', 'translation', translationZh.translation);
    await i18n.changeLanguage('zh');
    ready();

    renderReport();

    expect(screen.getByText(/默认先显示最近 7 天，展开后查看所选时间范围内的全部日期/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /查看所选范围全部日期（共 10 天）/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '按月用量' })).toBeInTheDocument();
    expect(screen.getByTestId('member-report-id')).toHaveTextContent('成员 ID');
  });
});

describe('theme tokens', () => {
  it('uses theme classes only: no hex colour, no inline colour style', () => {
    ready();

    const { container } = renderReport();

    const markup = container.innerHTML;
    expect(markup).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(markup).not.toMatch(/rgb\(|rgba\(/);
    expect(markup).not.toMatch(/style="[^"]*color/);
  });
});
