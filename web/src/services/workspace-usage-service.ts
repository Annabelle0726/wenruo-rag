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

import { registerNextServer } from '@/utils/register-server';
import { READ_QUERY_OPTIONS } from '@/utils/read-query-options';

/** The usage read model's views, as the server's own path suffixes. */
export const WORKSPACE_USAGE_ENDPOINTS = [
  'my',
  'summary',
  'members',
  'member-report',
  'daily',
  'monthly',
  'models',
  'quota',
] as const;

export type WorkspaceUsageEndpoint = (typeof WORKSPACE_USAGE_ENDPOINTS)[number];

type UsageQuery = Record<string, string | number | boolean | undefined>;

/**
 * Renders a query string, dropping absent values.
 *
 * The range bounds are validated on the server (a window longer than 92 days is
 * refused), so an unset bound is simply omitted and the server's default window
 * applies - this layer never invents one. Only the endpoint's own whitelisted
 * parameters are ever put here, because the server refuses an unknown one.
 */
const withQuery = (path: string, query: UsageQuery = {}) => {
  const search = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    // `tenantId` travels in the path, `skipGlobalErrorNotification` in the request config,
    // and `memberUserId` is a CLIENT-side cache key: the server names a member with
    // `user_id`, and a second name for the same thing is refused as an unknown parameter
    // rather than ignored, so it must never reach the wire.
    if (
      key === 'skipGlobalErrorNotification' ||
      key === 'tenantId' ||
      key === 'memberUserId'
    ) {
      return;
    }
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  });
  const suffix = search.toString();
  return suffix ? `${path}?${suffix}` : path;
};

const usagePath = (
  tenantId: string,
  endpoint: WorkspaceUsageEndpoint,
  query?: UsageQuery,
) =>
  withQuery(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/usage/${endpoint}`,
    query,
  );

const rawUsageService = registerNextServer({
  myUsage: {
    url: (config: { tenantId: string } & UsageQuery) =>
      usagePath(config.tenantId, 'my', config),
    method: 'get',
  },
  workspaceSummary: {
    url: (config: { tenantId: string } & UsageQuery) =>
      usagePath(config.tenantId, 'summary', config),
    method: 'get',
  },
  memberBreakdown: {
    url: (config: { tenantId: string } & UsageQuery) =>
      usagePath(config.tenantId, 'members', config),
    method: 'get',
  },
  // The member is named with `user_id`, the same parameter `/usage/quota` already
  // accepts for naming one member; the server refuses both spellings at once.
  memberReport: {
    url: (config: { tenantId: string } & UsageQuery) =>
      usagePath(config.tenantId, 'member-report', config),
    method: 'get',
  },
  dailySeries: {
    url: (config: { tenantId: string } & UsageQuery) =>
      usagePath(config.tenantId, 'daily', config),
    method: 'get',
  },
  monthlySeries: {
    url: (config: { tenantId: string } & UsageQuery) =>
      usagePath(config.tenantId, 'monthly', config),
    method: 'get',
  },
  recordedModelBreakdown: {
    url: (config: { tenantId: string } & UsageQuery) =>
      usagePath(config.tenantId, 'models', config),
    method: 'get',
  },
  quotaStatus: {
    url: (config: { tenantId: string } & UsageQuery) =>
      usagePath(config.tenantId, 'quota', config),
    method: 'get',
  },
  // The write takes a NATIVE axios config (second call argument), so the patch
  // travels in `data` and the revision in `headers` - the two can never be
  // confused for one another the way a single merged object invites.
  updateUsageBudget: {
    url: (config: { tenantId: string }) =>
      `/api/v1/tenants/${encodeURIComponent(config.tenantId)}/usage-budget`,
    method: 'put',
  },
});

/**
 * Marks a usage call as owning its own error surface.
 *
 * Two consequences, both deliberate:
 *
 * 1. `skipGlobalErrorNotification` keeps a failing read model OUT of the global
 *    toast. The error is NOT hidden - the Usage & Operations views render it in
 *    place, with the reason and a retry, which is where a reader looking at an
 *    empty figure will actually see it. What it stops is one transient toast per
 *    endpoint per retry for a surface that has seven of them.
 * 2. The native axios config is used, so the flag travels on the request CONFIG
 *    (where the interceptor reads it) rather than inside the request body, which
 *    is where `registerNextServer` puts a plain argument on a GET.
 */
const owningTheErrorSurface = (
  call: (config: any, useAxiosNativeConfig?: boolean) => Promise<any>,
) => {
  return (config: Record<string, any>) =>
    call({ ...config, skipGlobalErrorNotification: true }, true);
};

const workspaceUsageService = {
  myUsage: owningTheErrorSurface(rawUsageService.myUsage),
  workspaceSummary: owningTheErrorSurface(rawUsageService.workspaceSummary),
  memberBreakdown: owningTheErrorSurface(rawUsageService.memberBreakdown),
  memberReport: owningTheErrorSurface(rawUsageService.memberReport),
  dailySeries: owningTheErrorSurface(rawUsageService.dailySeries),
  monthlySeries: owningTheErrorSurface(rawUsageService.monthlySeries),
  recordedModelBreakdown: owningTheErrorSurface(
    rawUsageService.recordedModelBreakdown,
  ),
  quotaStatus: owningTheErrorSurface(rawUsageService.quotaStatus),
  /**
   * `PUT /tenants/<id>/usage-budget` with `If-Match: <policy_revision>`.
   *
   * The existing budget endpoint, not a second one: U3 configures rules that
   * already exist. It is the ONE usage call that must NOT swallow its own error
   * surface - a conflict is a state the editor renders - so it keeps the global
   * notification path and the caller inspects `code`/`error_type` itself.
   */
  updateUsageBudget: (
    tenantId: string,
    patch: Record<string, unknown>,
    revision: string,
  ) =>
    rawUsageService.updateUsageBudget(
      { tenantId, data: patch, headers: { 'If-Match': revision } },
      true,
    ),
};

export default workspaceUsageService;

/**
 * Retry policy for the usage reads.
 *
 * The policy itself lives in `@/utils/read-query-options`, because the
 * provider-health read is a workspace read model with exactly the same
 * requirements and two copies of it would drift. The name is kept so every
 * existing caller and its documentation stay true.
 */
export const USAGE_QUERY_OPTIONS = READ_QUERY_OPTIONS;
