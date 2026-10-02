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

// This file contains `jest.mock`, so it is transformed through the babel path: fixtures
// are declared locally rather than imported. `user-service.test.ts` uses the same pattern.

const mockGet = jest.fn();
const mockCall = jest.fn();

// `register-server` reaches the network through `@/utils/next-request`, whose default
// export is callable AND carries the verb methods.
jest.mock('@/utils/next-request', () => ({
  __esModule: true,
  default: Object.assign((...args: unknown[]) => mockCall(...args), {
    get: (...args: unknown[]) => mockGet(...args),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
    patch: jest.fn(),
  }),
}));

import workspaceUsageService from '../workspace-usage-service';

const urlOfLastCall = (): string => {
  // The registrar hands the transport a config object whose `url` is the path this module
  // BUILT (query string included), so that is what the assertions read.
  const calls = [...mockGet.mock.calls, ...mockCall.mock.calls];
  expect(calls.length).toBeGreaterThan(0);
  const first = calls[calls.length - 1][0];
  if (typeof first === 'string') {
    return first;
  }
  return String((first as { url?: string })?.url ?? '');
};

beforeEach(() => {
  mockGet.mockReset();
  mockGet.mockResolvedValue({ data: { code: 0 } });
});

describe('the usage query string carries only what the endpoint accepts', () => {
  it('names a member with user_id and keeps the client cache key off the wire', () => {
    workspaceUsageService.memberReport({
      tenantId: 'ws-1',
      user_id: 'member-1',
      memberUserId: 'member-1',
      start_day: '2026-03-01',
      end_day: '2026-03-31',
    });

    const url = urlOfLastCall();
    expect(url).toContain('/api/v1/tenants/ws-1/usage/member-report');
    expect(url).toContain('user_id=member-1');
    expect(url).toContain('start_day=2026-03-01');
    expect(url).toContain('end_day=2026-03-31');
    // The server refuses an unknown parameter, so a second name for the member would turn
    // a working read into a refusal.
    expect(url).not.toContain('memberUserId');
  });

  it('does the same for the member-scoped quota read', () => {
    workspaceUsageService.quotaStatus({ tenantId: 'ws-1', user_id: 'member-2', memberUserId: 'member-2' });

    const url = urlOfLastCall();
    expect(url).toContain('/api/v1/tenants/ws-1/usage/quota');
    expect(url).toContain('user_id=member-2');
    expect(url).not.toContain('memberUserId');
  });

  it('never puts the workspace id or the error-surface flag in the query', () => {
    workspaceUsageService.workspaceSummary({ tenantId: 'ws-9', start_day: '2026-03-01' });

    const url = urlOfLastCall();
    expect(url).toContain('/api/v1/tenants/ws-9/usage/summary');
    expect(url).toContain('start_day=2026-03-01');
    expect(url).not.toContain('tenantId');
    expect(url).not.toContain('skipGlobalErrorNotification');
  });
});
