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
  IMemberReportData,
  IQuotaStatusData,
  IUsageEnvelope,
  IUsageMonthRangeParams,
  IUsagePageParams,
  IUsageRangeParams,
  UsageView,
} from '@/interfaces/database/workspace-usage';
import workspaceUsageService, {
  USAGE_QUERY_OPTIONS,
} from '@/services/workspace-usage-service';
import { useFetchTenantInfo } from '@/hooks/use-user-setting-request';
import { getActiveTenantId } from '@/utils/active-tenant';
import { isSuccess } from '@/pages/user-setting/setting-team/usage-policy-validation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

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

const unwrap = (body: any): IUsageEnvelope | undefined =>
  body?.code === 0 ? (body.data as IUsageEnvelope) : undefined;

/**
 * Which workspace the usage pages read.
 *
 * It is the workspace the SERVER resolved for this caller (`/v1/user/tenant_info`
 * mirrors it into the selection), never the caller's user id: on this platform a
 * workspace key and a member key are different identity domains and can even
 * share a value, so an id comparison would prove nothing.
 *
 * It is read through the tenant-info QUERY rather than straight out of
 * localStorage because the value must be REACTIVE: read once during the first
 * render it is still empty, and a query disabled by an empty id would never fire
 * when the id arrives.
 */
export const useActiveUsageTenantId = (): string | undefined => {
  const { data: tenantInfo } = useFetchTenantInfo();
  return tenantInfo?.tenant_id || getActiveTenantId() || undefined;
};

/**
 * One read of the usage model.
 *
 * Every view goes through here so the four rules that apply to all of them are
 * stated once: the workspace must be resolved before anything is requested, the
 * cache key carries that workspace, the retry policy refuses to hammer a refusal
 * (`USAGE_QUERY_OPTIONS`), and the response is unwrapped only when the server
 * reports success - a payload with a non-zero `code` is NOT data.
 */
const useUsageView = (
  view: UsageView,
  params: object,
  fetcher: (config: Record<string, unknown>) => Promise<any>,
) => {
  const tenantId = useActiveUsageTenantId();
  const { data, isFetching, refetch, error } = useQuery({
    queryKey: WorkspaceUsageKeys.view(tenantId, view, params),
    enabled: Boolean(tenantId),
    ...USAGE_QUERY_OPTIONS,
    queryFn: async () => {
      const { data: body } = await fetcher({ tenantId, ...params });
      return unwrap(body);
    },
  });

  return { data, loading: isFetching, refetch, error };
};

/** `GET /tenants/<id>/usage/my` - the caller's own usage. */
export const useFetchMyUsage = (params: IUsageRangeParams = {}) =>
  useUsageView('my_usage', params, workspaceUsageService.myUsage);

/** `GET /tenants/<id>/usage/summary` - the workspace aggregate (OWNER/ADMIN). */
export const useFetchWorkspaceUsageSummary = (params: IUsageRangeParams = {}) =>
  useUsageView('workspace_summary', params, workspaceUsageService.workspaceSummary);

/** `GET /tenants/<id>/usage/members` - the per-member breakdown (OWNER/ADMIN). */
export const useFetchMemberUsageBreakdown = (
  params: IUsageRangeParams & IUsagePageParams = {},
) => useUsageView('member_breakdown', params, workspaceUsageService.memberBreakdown);

/**
 * `GET /tenants/<id>/usage/member-report` - ONE member's window.
 *
 * The member is named with `user_id`, the parameter the quota read already uses to
 * name one member, and the range is the page's own window so the report and the
 * sections above it describe the same interval. Naming nobody reads the caller's
 * own report: that default is the SERVER's rule (the scope resolver resolves an
 * unnamed subject to the actor), not a second rule invented here.
 */
export const useFetchMemberReport = (
  memberUserId?: string,
  params: IUsageRangeParams & IUsagePageParams = {},
) =>
  useUsageView(
    'member_report',
    { ...params, memberUserId },
    (config) =>
      workspaceUsageService.memberReport({
        ...config,
        ...(memberUserId ? { user_id: memberUserId } : {}),
      }),
  ) as {
    data?: IUsageEnvelope & { data?: IMemberReportData };
    loading: boolean;
    refetch: () => Promise<{ error?: unknown } | undefined>;
    error: unknown;
  };

/** `GET /tenants/<id>/usage/daily` - one bucket per day (OWNER/ADMIN). */
export const useFetchDailyUsageSeries = (params: IUsageRangeParams = {}) =>
  useUsageView('daily_series', params, workspaceUsageService.dailySeries);

/**
 * `GET /tenants/<id>/usage/monthly` - one bucket per month (OWNER/ADMIN).
 *
 * Kept in its own query: month buckets must never be added to day buckets,
 * because one reservation increments a day row AND a month row.
 */
export const useFetchMonthlyUsageSeries = (
  params: IUsageMonthRangeParams = {},
) => useUsageView('monthly_series', params, workspaceUsageService.monthlySeries);

/** `GET /tenants/<id>/usage/models` - by RECORDED model name (OWNER/ADMIN). */
export const useFetchRecordedModelUsage = (
  params: IUsageRangeParams & IUsagePageParams = {},
) =>
  useUsageView(
    'recorded_model_breakdown',
    params,
    workspaceUsageService.recordedModelBreakdown,
  );

/**
 * `GET /tenants/<id>/usage/quota` - the current period's limits and occupancy.
 *
 * A NORMAL member may read their own; naming another member is refused by the
 * server, so the Usage Policy destination only passes a member when it is allowed
 * to.
 */
export const useFetchQuotaStatus = (memberUserId?: string) =>
  useUsageView(
    'quota_status',
    { memberUserId },
    (config) =>
      workspaceUsageService.quotaStatus({
        ...config,
        ...(memberUserId ? { user_id: memberUserId } : {}),
      }),
  ) as {
    data?: IUsageEnvelope & { data?: IQuotaStatusData };
    loading: boolean;
    refetch: () => Promise<{ error?: unknown } | undefined>;
    error: unknown;
  };

/**
 * Saves a policy patch with the revision the reader was shown.
 *
 * It is a mutation rather than a plain request because the outcome drives the
 * editor's state machine: `code=0` alone is a success (HTTP 200 does not mean a
 * write happened - a conflict arrives as 200 too), and the caller must be able to
 * tell a conflict from a failure from an unknown result. It NEVER auto-retries:
 * a timeout leaves the outcome unknown, and re-sending a policy write that may
 * already have landed is exactly what `If-Match` exists to prevent.
 *
 * On success the workspace's quota and usage caches are invalidated by KEY, so a
 * save in one workspace cannot refresh another's data.
 */
export const useUpdateUsagePolicy = () => {
  const queryClient = useQueryClient();
  const tenantId = useActiveUsageTenantId();

  const mutation = useMutation({
    retry: false,
    mutationFn: async ({
      patch,
      revision,
    }: {
      patch: Record<string, number>;
      revision: string;
    }) => {
      const { data: body } = await workspaceUsageService.updateUsageBudget(
        tenantId as string,
        patch,
        revision,
      );
      return body;
    },
    onSuccess: (body) => {
      if (!isSuccess(body) || !tenantId) {
        return;
      }
      queryClient.invalidateQueries({
        queryKey: WorkspaceUsageKeys.all(tenantId),
      });
    },
  });

  return {
    save: mutation.mutateAsync,
    saving: mutation.isPending,
    reset: mutation.reset,
    tenantId,
  };
};
