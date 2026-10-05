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

const STORAGE_KEY = 'ragflow_active_tenant_id';

/**
 * The workspace the client is operating in, sent as `X-Tenant-Id` on every
 * request.
 *
 * The server is the authority - it persists the selection and only honours a
 * header naming a workspace the caller belongs to - so this exists to make a
 * switch take effect on the next request instead of the next reload.
 *
 * Kept in `localStorage` rather than a store because the request interceptor,
 * which runs outside React, is the only consumer.
 */
export const getActiveTenantId = (): string | null => {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    // Private-mode browsers can deny storage; the server-side selection still
    // applies, so the session simply loses the extra hint.
    return null;
  }
};

export const setActiveTenantId = (tenantId: string | null | undefined) => {
  try {
    if (tenantId) {
      window.localStorage.setItem(STORAGE_KEY, tenantId);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // See getActiveTenantId.
  }
};
