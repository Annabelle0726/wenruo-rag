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

/**
 * The retry policy for a workspace READ MODEL.
 *
 * One policy, in one place, because two read surfaces now depend on the same
 * behaviour: a read model is an idempotent GET, but retrying a REFUSAL or a
 * MISSING ROUTE cannot succeed and only multiplies the noise - React Query's
 * default of two retries turns one unreachable read model into three requests. A
 * transient failure (a timeout, a 503, a dropped connection) is worth exactly one
 * more attempt; after that the view reports the failure and offers a retry.
 *
 * The app-level QueryClient already disables refetch-on-window-focus, so this
 * policy plus that default is the whole refresh behaviour: fetch on mount, plus a
 * refetch when a surface explicitly asks for one.
 */
export const READ_QUERY_OPTIONS = {
  retry: (failureCount: number, error: unknown) => {
    const status =
      (error as { response?: { status?: number } })?.response?.status ?? 0;
    const permanent = status >= 400 && status !== 503;
    return !permanent && failureCount < 1;
  },
};
