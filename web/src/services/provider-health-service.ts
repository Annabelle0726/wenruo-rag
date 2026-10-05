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

export interface IProviderIncidentQuery {
  tenantId: string;
  limit?: number;
  offset?: number;
  resolved_window_days?: number;
}

/**
 * Renders the query string, dropping absent values.
 *
 * The server refuses an unknown parameter, so only the three it whitelists are
 * ever put here and an unset one is omitted rather than defaulted client-side -
 * the server owns the window and the page size, and this layer must not invent a
 * different one.
 */
const incidentsPath = (config: IProviderIncidentQuery) => {
  const search = new URLSearchParams();
  if (config.limit !== undefined) {
    search.set('limit', String(config.limit));
  }
  if (config.offset !== undefined) {
    search.set('offset', String(config.offset));
  }
  if (config.resolved_window_days !== undefined) {
    search.set('resolved_window_days', String(config.resolved_window_days));
  }
  const suffix = search.toString();
  const path = `/api/v1/tenants/${encodeURIComponent(config.tenantId)}/provider-health/incidents`;
  return suffix ? `${path}?${suffix}` : path;
};

const rawProviderHealthService = registerNextServer({
  incidents: {
    url: (config: IProviderIncidentQuery) => incidentsPath(config),
    method: 'get',
  },
});

/**
 * The one read this domain has.
 *
 * It keeps its error OUT of the global toast (`skipGlobalErrorNotification`) for
 * the same reason the usage reads do: a refusal or a failure has to be visible
 * WHERE the reader is looking, because the alternative - a toast that fades and a
 * view that renders as "nothing recorded" - is the exact confusion this surface
 * exists to prevent. The hook turns a non-zero `code` into a thrown error, so a
 * refused read can never be mistaken for an empty one.
 *
 * The native axios config is used so the flag travels on the request CONFIG,
 * where the interceptor reads it.
 */
const providerHealthService = {
  incidents: (config: IProviderIncidentQuery) =>
    rawProviderHealthService.incidents(
      { ...config, skipGlobalErrorNotification: true },
      true,
    ),
};

export default providerHealthService;
