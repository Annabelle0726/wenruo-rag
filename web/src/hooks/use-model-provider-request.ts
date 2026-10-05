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

import llmService from '@/services/llm-service';
import { IAddedModel } from '@/interfaces/database/llm';
import { useQuery } from '@tanstack/react-query';

/**
 * Every model-provider query key this domain owns.
 */
export const ModelProviderKeys = {
  addedModels: () => ['modelProviders', 'addedModels'] as const,
};

/**
 * The workspace's CONFIGURED models, which is what the Model Providers overview
 * groups by provider.
 *
 * It reads `GET /api/v1/models` - an endpoint that already exists and is already
 * used by the model settings page - and deliberately NOT the provider-instance
 * endpoint, whose payload carries a credential field. Nothing here can leak a
 * key because none is ever requested, and the overview renders provider name,
 * instance name, model name, capability and configuration status only.
 */
export const useFetchConfiguredModels = () => {
  const { data, isFetching, refetch, error } = useQuery({
    queryKey: ModelProviderKeys.addedModels(),
    queryFn: async () => {
      const { data: body } = await llmService.listAllAddedModels();
      const payload = body?.data;
      // The endpoint answers with a bare array; older shapes nested it under
      // `models`. Accepting both keeps a stale backend from rendering as empty.
      const rows: IAddedModel[] = Array.isArray(payload)
        ? payload
        : Array.isArray(payload?.models)
          ? payload.models
          : [];
      return rows;
    },
  });

  return { data: data ?? [], loading: isFetching, refetch, error };
};
