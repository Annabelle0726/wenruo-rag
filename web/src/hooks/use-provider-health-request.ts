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
  IProviderIncidentView,
} from '@/interfaces/database/provider-health';
import { useActiveUsageTenantId } from '@/hooks/use-workspace-usage-request';
import providerHealthService from '@/services/provider-health-service';
import { READ_QUERY_OPTIONS } from '@/utils/read-query-options';
import { useQuery } from '@tanstack/react-query';

/**
 * Every provider-health query key this domain owns.
 *
 * The workspace is part of the key, so switching workspace re-keys the cache
 * instead of showing one workspace's incidents under another's name. The PAGE and
 * the NOTIFICATION BELL both call the hook below with no parameters, so they share
 * this one cache entry and therefore one request - the bell is not a second read of
 * the same rows with its own state model.
 */
export const ProviderHealthKeys = {
  all: (tenantId?: string) => ['providerHealth', tenantId] as const,
  incidents: (tenantId: string | undefined, params: unknown) =>
    ['providerHealth', tenantId, 'incidents', params] as const,
};

/**
 * Why a provider-health read did not produce data.
 *
 * `Refused` and `Unavailable` are separated because they are different facts and
 * deserve different copy: a refusal cannot be retried into success, and telling a
 * member "the read failed, try again" when the answer was "you may not see this"
 * is the same class of lie as showing them an empty list.
 */
export const ProviderHealthErrorKind = {
  Refused: 'refused',
  Unavailable: 'unavailable',
} as const;

export type ProviderHealthErrorKind =
  (typeof ProviderHealthErrorKind)[keyof typeof ProviderHealthErrorKind];

export class ProviderHealthReadError extends Error {
  kind: ProviderHealthErrorKind;
  code: number | undefined;

  constructor(kind: ProviderHealthErrorKind, code?: number) {
    super(`provider health read ${kind}${code === undefined ? '' : ` (code ${code})`}`);
    this.name = 'ProviderHealthReadError';
    this.kind = kind;
    this.code = code;
  }
}

const fromBodyCode = (code: number): ProviderHealthErrorKind =>
  // 108 is this API's permission refusal, and 401/403 are the transport's own.
  code === 108 || code === 401 || code === 403
    ? ProviderHealthErrorKind.Refused
    : ProviderHealthErrorKind.Unavailable;

const fromTransport = (error: unknown): ProviderHealthErrorKind => {
  const status =
    (error as { response?: { status?: number } })?.response?.status ?? 0;
  return status === 401 || status === 403
    ? ProviderHealthErrorKind.Refused
    : ProviderHealthErrorKind.Unavailable;
};

/**
 * One read of the workspace's provider incidents.
 *
 * Three rules, stated once because both consumers obey them:
 *
 * 1. the workspace must be resolved before anything is requested (`enabled`), so a
 *    read is never sent for an unknown workspace;
 * 2. a non-zero `code` is NOT data and NOT emptiness - it is thrown, so a refused
 *    or failed read can never render as "no incidents recorded";
 * 3. `staleTime` keeps the page and the bell from firing the same request twice in
 *    one visit, and the bell explicitly refetches when its drawer opens.
 */
export const useFetchProviderIncidents = (params: object = {}) => {
  const tenantId = useActiveUsageTenantId();
  const { data, isPending, isFetching, refetch, error } = useQuery({
    queryKey: ProviderHealthKeys.incidents(tenantId, params),
    enabled: Boolean(tenantId),
    staleTime: 60_000,
    ...READ_QUERY_OPTIONS,
    queryFn: async (): Promise<IProviderIncidentView> => {
      try {
        const { data: body } = await providerHealthService.incidents({
          tenantId: tenantId as string,
          ...params,
        });
        if (!body || body.code !== 0 || !body.data) {
          throw new ProviderHealthReadError(fromBodyCode(body?.code ?? -1), body?.code);
        }
        return body.data as IProviderIncidentView;
      } catch (thrown) {
        if (thrown instanceof ProviderHealthReadError) {
          throw thrown;
        }
        throw new ProviderHealthReadError(fromTransport(thrown));
      }
    },
  });

  return {
    data,
    /** True while the workspace is unresolved OR a read is in flight. */
    loading: Boolean(tenantId) && (isPending || isFetching),
    /** True while no request has been made at all - the workspace is unknown. */
    idle: !tenantId,
    error: error as ProviderHealthReadError | null,
    refetch,
  };
};
