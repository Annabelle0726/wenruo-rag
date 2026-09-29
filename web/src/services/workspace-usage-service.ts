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

/** The seven U1 usage views, as the server's own path suffixes. */
export const WORKSPACE_USAGE_ENDPOINTS = [
  'my',
  'summary',
  'members',
  'daily',
  'monthly',
  'models',
  'quota',
] as const;

export type WorkspaceUsageEndpoint = (typeof WORKSPACE_USAGE_ENDPOINTS)[number];

type UsageQuery = Record<string, string | number | undefined>;

/**
 * Renders a query string, dropping absent values.
 *
 * The range bounds are validated on the server (a window longer than 92 days is
 * refused), so an unset bound is simply omitted and the server's default window
 * applies - this layer never invents one.
 */
const withQuery = (path: string, query: UsageQuery = {}) => {
  const search = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
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

/**
 * The U1 usage read model: seven GET endpoints, all read-only.
 *
 * They are the ONLY source the Usage & Operations pages read usage from. Nothing
 * here writes, and the server re-checks a live workspace membership on every
 * call, so a refusal arrives as HTTP 200 + `code: 108` rather than as a 403.
 */
const workspaceUsageService = registerNextServer({
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
});

export default workspaceUsageService;
