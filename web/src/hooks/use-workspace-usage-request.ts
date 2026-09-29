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
  IQuotaStatusData,
  IUsageEnvelope,
  IUsageMonthRangeParams,
  IUsagePageParams,
  IUsageRangeParams,
  UsageView,
} from '@/interfaces/database/workspace-usage';
import workspaceUsageService from '@/services/workspace-usage-service';
import { getActiveTenantId } from '@/utils/active-tenant';
import { useQuery } from '@tanstack/react-query';

/**
 * Every usage query key this domain owns.
 *
 * The workspace id is part of the key, so switching workspace re-keys the cache
 * instead of overwriting one workspace's usage with another's.
 */
export const WorkspaceUsageKeys = {
  /** Prefix form: every usage query of one workspace, whatever the view. */
  all: (tenantId?: string) => ['workspaceUsage', tenantId] as const,
  view: (tenantId: string | undefined, view: UsageView, params: unknown) =>
    ['workspaceUsage', tenantId, view, params] as const,
};

const ok = (code: unknown) => code === 0;

const unwrap = (body: any): IUsageEnvelope | undefined =>
  ok(body?.code) ? (body.data as IUsageEnvelope) : undefined;

/**
 * Which workspace the usage pages read.
 *
 * It is the SELECTED workspace, never the caller's user id: on this platform a
 * workspace key and a member key are different identity domains, and they can
 * even share a value, so an id comparison would prove nothing.
 */
export const useActiveUsageTenantId = (): string | undefined =>
  getActiveTenantId() || undefined;

/**
 * `GET /tenants/<id>/usage/my` - the caller's own usage.
 *
 * The server forces the subject to the caller for a NORMAL member, so this hook
 * cannot be pointed at someone else's rows even if a caller tried.
 */
export const useFetchMyUsage = (params: IUsageRangeParams = {}) => {
  const tenantId = useActiveUsageTenantId();
  const { data, isFetching, refetch, error } = useQuery({
    queryKey: WorkspaceUsageKeys.view(tenantId, 'my_usage', params),
    enabled: Boolean(tenantId),
    queryFn: async () => {
      const { data: body } = await workspaceUsageService.myUsage({
        tenantId,
        ...params,
      });
      return unwrap(body);
    },
  });

  return { data, loading: isFetching, refetch, error };
};

/** `GET /tenants/<id>/usage/summary` - the workspace aggregate (OWNER/ADMIN). */
export const useFetchWorkspaceUsageSummary = (params: IUsageRangeParams = {}) => {
  const tenantId = useActiveUsageTenantId();
  const { data, isFetching, refetch, error } = useQuery({
    queryKey: WorkspaceUsageKeys.view(tenantId, 'workspace_summary', params),
    enabled: Boolean(tenantId),
    queryFn: async () => {
      const { data: body } = await workspaceUsageService.workspaceSummary({
        tenantId,
        ...params,
      });
      return unwrap(body);
    },
  });

  return { data, loading: isFetching, refetch, error };
};

/** `GET /tenants/<id>/usage/members` - the per-member breakdown (OWNER/ADMIN). */
export const useFetchMemberUsageBreakdown = (
  params: IUsageRangeParams & IUsagePageParams = {},
) => {
  const tenantId = useActiveUsageTenantId();
  const { data, isFetching, refetch, error } = useQuery({
    queryKey: WorkspaceUsageKeys.view(tenantId, 'member_breakdown', params),
    enabled: Boolean(tenantId),
    queryFn: async () => {
      const { data: body } = await workspaceUsageService.memberBreakdown({
        tenantId,
        ...params,
      });
      return unwrap(body);
    },
  });

  return { data, loading: isFetching, refetch, error };
};

/** `GET /tenants/<id>/usage/daily` - one bucket per day (OWNER/ADMIN). */
export const useFetchDailyUsageSeries = (params: IUsageRangeParams = {}) => {
  const tenantId = useActiveUsageTenantId();
  const { data, isFetching, refetch, error } = useQuery({
    queryKey: WorkspaceUsageKeys.view(tenantId, 'daily_series', params),
    enabled: Boolean(tenantId),
    queryFn: async () => {
      const { data: body } = await workspaceUsageService.dailySeries({
        tenantId,
        ...params,
      });
      return unwrap(body);
    },
  });

  return { data, loading: isFetching, refetch, error };
};

/**
 * `GET /tenants/<id>/usage/monthly` - one bucket per month (OWNER/ADMIN).
 *
 * Kept in its own query: month buckets must never be added to day buckets,
 * because one reservation increments a day row AND a month row.
 */
export const useFetchMonthlyUsageSeries = (
  params: IUsageMonthRangeParams = {},
) => {
  const tenantId = useActiveUsageTenantId();
  const { data, isFetching, refetch, error } = useQuery({
    queryKey: WorkspaceUsageKeys.view(tenantId, 'monthly_series', params),
    enabled: Boolean(tenantId),
    queryFn: async () => {
      const { data: body } = await workspaceUsageService.monthlySeries({
        tenantId,
        ...params,
      });
      return unwrap(body);
    },
  });

  return { data, loading: isFetching, refetch, error };
};

/** `GET /tenants/<id>/usage/models` - by RECORDED model name (OWNER/ADMIN). */
export const useFetchRecordedModelUsage = (
  params: IUsageRangeParams & IUsagePageParams = {},
) => {
  const tenantId = useActiveUsageTenantId();
  const { data, isFetching, refetch, error } = useQuery({
    queryKey: WorkspaceUsageKeys.view(
      tenantId,
      'recorded_model_breakdown',
      params,
    ),
    enabled: Boolean(tenantId),
    queryFn: async () => {
      const { data: body } = await workspaceUsageService.recordedModelBreakdown(
        { tenantId, ...params },
      );
      return unwrap(body);
    },
  });

  return { data, loading: isFetching, refetch, error };
};

/**
 * `GET /tenants/<id>/usage/quota` - the current period's limits and occupancy.
 *
 * A NORMAL member may read their own; naming another member is refused by the
 * server, so the Usage Policy view only passes a member when it is allowed to.
 */
export const useFetchQuotaStatus = (memberUserId?: string) => {
  const tenantId = useActiveUsageTenantId();
  const { data, isFetching, refetch, error } = useQuery({
    queryKey: WorkspaceUsageKeys.view(tenantId, 'quota_status', {
      memberUserId,
    }),
    enabled: Boolean(tenantId),
    queryFn: async () => {
      const { data: body } = await workspaceUsageService.quotaStatus({
        tenantId,
        ...(memberUserId ? { user_id: memberUserId } : {}),
      });
      return unwrap(body) as IUsageEnvelope & { data?: IQuotaStatusData };
    },
  });

  return { data, loading: isFetching, refetch, error };
};
