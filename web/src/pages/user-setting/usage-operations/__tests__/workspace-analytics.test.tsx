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

import { fireEvent, render, screen } from '@testing-library/react';
import i18n from 'i18next';
import translationZh from '@/locales/zh';
import WorkspaceAnalytics from '../workspace-analytics';

const mockSummary = jest.fn();
const mockMembers = jest.fn();
const mockModels = jest.fn();
const mockDaily = jest.fn();
const mockMonthly = jest.fn();
const mockMemberReport = jest.fn();

jest.mock('@/hooks/use-workspace-usage-request', () => ({
  useFetchWorkspaceUsageSummary: () => mockSummary(),
  useFetchMemberUsageBreakdown: () => mockMembers(),
  useFetchRecordedModelUsage: () => mockModels(),
  useFetchDailyUsageSeries: () => mockDaily(),
  useFetchMonthlyUsageSeries: () => mockMonthly(),
  useFetchMemberReport: (...args: unknown[]) => mockMemberReport(...args),
}));

jest.mock('../components/usage-range-filter', () => ({
  useUsageDayWindow: (days: number) => ({
    start_day: '2026-03-01',
    end_day: days === 7 ? '2026-03-07' : '2026-03-31',
  }),
  UsageRangeFilter: () => null,
  USAGE_RANGE_PRESETS: [7, 30, 90],
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

const dayPeriod = (index: number) => `2026-03-${String(index + 1).padStart(2, '0')}`;

const dayBuckets = (count: number) =>
  Array.from({ length: count }, (_, index) => ({
    period: dayPeriod(index),
    attempted_calls: index + 1,
    accounting: accounting({ attempted_calls: index + 1 }),
  }));

const envelope = (accountingBlock: ITestAccounting = accounting()) => ({
  view: 'daily_series',
  scope: {},
  period: { start_day: '2026-03-01', end_day: '2026-03-31', days: 31 },
  accounting: accountingBlock,
  cost: {},
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
});

beforeEach(() => {
  jest.clearAllMocks();
  void i18n.changeLanguage('en');
  mockSummary.mockReturnValue({
    data: { data: {}, accounting: accounting() },
    loading: false,
    error: null,
    refetch: jest.fn(),
  });
  mockMembers.mockReturnValue({
    data: {
      data: {
        members: [
          {
            user_id: 'member-a',
            nickname: 'Member A',
            name_available: true,
            live_member: true,
            role: 'normal',
            accounting: accounting(),
          },
          {
            user_id: 'member-b',
            nickname: 'Member B',
            name_available: true,
            live_member: false,
            role: null,
            accounting: accounting({ attempted_calls: 1 }),
          },
        ],
        total_members: 2,
        limit: 50,
        offset: 0,
        truncated: false,
        not_answered: '',
      },
    },
    loading: false,
    error: null,
    refetch: jest.fn(),
  });
  mockModels.mockReturnValue({
    data: {
      data: {
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
        not_answered: '',
      },
    },
    loading: false,
    error: null,
    refetch: jest.fn(),
  });
  mockDaily.mockReturnValue({
    data: {
      data: {
        buckets: dayBuckets(10),
        granularity: 'day',
        zero_filled: 'every period in the requested window is present',
      },
    },
    loading: false,
    error: null,
    refetch: jest.fn(),
  });
  mockMonthly.mockReturnValue({
    data: {
      data: {
        buckets: [
          { period: '2026-03', attempted_calls: 9, accounting: accounting() },
          { period: '2026-02', attempted_calls: 4, accounting: accounting() },
        ],
        granularity: 'month',
        zero_filled: 'every period in the requested window is present',
      },
    },
    loading: false,
    error: null,
    refetch: jest.fn(),
  });
  mockMemberReport.mockReturnValue({
    data: {
      ...envelope(),
      data: {
        member: {
          user_id: 'member-a',
          nickname: 'Member A',
          name_available: true,
          live_member: true,
          role: 'normal',
        },
        daily: { buckets: dayBuckets(10), granularity: 'day', zero_filled: 'server text' },
        monthly: {
          buckets: [{ period: '2026-03', attempted_calls: 9, accounting: accounting() }],
          granularity: 'month',
          zero_filled: 'server text',
        },
        models: {
          models: [
            {
              recorded_model_name: 'embed-x',
              bucket: 'embed-x',
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
          not_answered: '',
        },
        not_answered: '',
      },
    },
    loading: false,
    error: null,
    refetch: jest.fn(),
  });
});

const renderPage = () => render(<WorkspaceAnalytics />);

const dayRowsRendered = () =>
  Array.from({ length: 10 }, (_, index) => dayPeriod(index)).filter(
    (period) => screen.queryByText(period) !== null,
  );

describe('the workspace daily block previews the latest seven days', () => {
  it('shows seven days, expands to the window and collapses back', () => {
    renderPage();

    expect(dayRowsRendered()).toHaveLength(7);
    expect(screen.queryByText('2026-03-01')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /View all dates/ }));
    expect(dayRowsRendered()).toHaveLength(10);
    expect(screen.getByText('2026-03-01')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Show only the latest/ }));
    expect(dayRowsRendered()).toHaveLength(7);
  });

  it('states the daily hint from the catalogue, not the server sentence', () => {
    renderPage();

    expect(screen.queryByText('every period in the requested window is present')).not.toBeInTheDocument();
    expect(screen.getByText(/Shows the latest 7 days first/)).toBeInTheDocument();
  });
});

describe('the workspace monthly block is an accordion', () => {
  it('is closed by default, opens on the header control, and closes again', () => {
    renderPage();

    expect(screen.queryByText('2026-02')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Monthly usage' }));
    expect(screen.getByText('2026-02')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Monthly usage' }));
    expect(screen.queryByText('2026-02')).not.toBeInTheDocument();
  });
});

describe('one member report at a time', () => {
  it('opens the report under the row that was clicked', () => {
    renderPage();

    expect(screen.queryByTestId('member-report-ready')).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByTestId('member-usage-toggle')[0]);

    expect(screen.getAllByTestId('member-report-ready')).toHaveLength(1);
    expect(mockMemberReport).toHaveBeenCalledWith('member-a', {
      start_day: '2026-03-01',
      end_day: '2026-03-31',
    });
  });

  it('closes the open report when another member is opened', () => {
    renderPage();

    fireEvent.click(screen.getAllByTestId('member-usage-toggle')[0]);
    fireEvent.click(screen.getAllByTestId('member-usage-toggle')[1]);

    expect(screen.getAllByTestId('member-report-ready')).toHaveLength(1);
    expect(mockMemberReport).toHaveBeenLastCalledWith('member-b', {
      start_day: '2026-03-01',
      end_day: '2026-03-31',
    });
  });

  it('closes the open report when its own row is clicked again', () => {
    renderPage();

    fireEvent.click(screen.getAllByTestId('member-usage-toggle')[0]);
    expect(screen.getAllByTestId('member-report-ready')).toHaveLength(1);

    fireEvent.click(screen.getAllByTestId('member-usage-toggle')[0]);
    expect(screen.queryByTestId('member-report-ready')).not.toBeInTheDocument();
  });

  it('labels a removed member row', () => {
    renderPage();

    expect(screen.getByText('No longer a member')).toBeInTheDocument();
  });
});

describe('theme tokens', () => {
  it('renders theme classes only: no hex colour, no inline colour style', () => {
    const { container } = renderPage();

    fireEvent.click(screen.getAllByTestId('member-usage-toggle')[0]);

    const markup = container.innerHTML;
    expect(markup).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(markup).not.toMatch(/rgb\(|rgba\(/);
    expect(markup).not.toMatch(/style="[^"]*color/);
  });
});

describe('the copy is translated', () => {
  it('renders the Chinese daily hint and controls', async () => {
    i18n.addResourceBundle('zh', 'translation', translationZh.translation);
    await i18n.changeLanguage('zh');

    renderPage();

    expect(screen.getByText(/默认先显示最近 7 天，展开后查看所选时间范围内的全部日期/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /查看所选范围全部日期（共 10 天）/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '按月用量' })).toBeInTheDocument();
  });
});
