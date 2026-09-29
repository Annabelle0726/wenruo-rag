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

import { Badge } from '@/components/ui/badge';
import { CardSkeleton } from '@/components/ui/skeleton';
import {
  CAPABILITY_LABEL_KEY,
  classifyProviderEndpoint,
  ProviderEndpointKind,
  sortCapabilities,
} from '@/constants/model-provider-endpoint';
import { useFetchConfiguredModels } from '@/hooks/use-model-provider-request';
import { IAddedModel } from '@/interfaces/database/llm';
import { cn } from '@/lib/utils';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

interface IProviderGroup {
  providerName: string;
  kind: ProviderEndpointKind;
  instances: string[];
  models: IAddedModel[];
  capabilities: string[];
}

const GROUP_ORDER: ProviderEndpointKind[] = ['managed', 'private'];

const GROUP_LABEL_KEY: Record<ProviderEndpointKind, string> = {
  managed: 'usage.providerGroupManaged',
  private: 'usage.providerGroupPrivate',
  unclassified: 'usage.providerGroupUnclassified',
};

const GROUP_HINT_KEY: Record<ProviderEndpointKind, string> = {
  managed: 'usage.providerGroupManagedHint',
  private: 'usage.providerGroupPrivateHint',
  unclassified: 'usage.providerGroupUnclassifiedHint',
};

const groupByProvider = (models: IAddedModel[]): IProviderGroup[] => {
  const groups = new Map<string, IProviderGroup>();

  models.forEach((model) => {
    const providerName = model.provider_name || '';
    const group = groups.get(providerName) ?? {
      providerName,
      kind: classifyProviderEndpoint(providerName),
      instances: [],
      models: [],
      capabilities: [],
    };
    if (model.instance_name && !group.instances.includes(model.instance_name)) {
      group.instances.push(model.instance_name);
    }
    group.models.push(model);
    group.capabilities.push(...(model.model_type ?? []));
    groups.set(providerName, group);
  });

  return Array.from(groups.values()).map((group) => ({
    ...group,
    capabilities: sortCapabilities(group.capabilities),
  }));
};

function CapabilityTag({ capability }: { capability: string }) {
  const { t } = useTranslation();
  const labelKey = CAPABILITY_LABEL_KEY[capability];

  return (
    <Badge className="rounded-[2px] text-[10px] font-normal" data-testid="provider-capability">
      {/* An unmapped type keeps its RAW name rather than disappearing. */}
      {labelKey ? t(labelKey) : capability}
    </Badge>
  );
}

function ProviderRow({ group }: { group: IProviderGroup }) {
  const { t } = useTranslation();
  const modelNames = group.models
    .map((model) => model.name)
    .filter(Boolean)
    .slice(0, 6);

  return (
    <li
      className="ceramic-relief flex flex-col gap-1.5 rounded-[2px] p-2.5"
      data-testid={`provider-row-${group.providerName}`}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="truncate text-sm text-text-primary">
          {group.providerName || t('usage.providerNameUnknown')}
        </span>
        <Badge className="shrink-0 rounded-[2px] text-[10px] font-normal">
          {t(GROUP_LABEL_KEY[group.kind])}
        </Badge>
      </div>

      <div className="flex flex-wrap gap-1">
        {group.capabilities.length > 0 ? (
          group.capabilities.map((capability) => (
            <CapabilityTag key={capability} capability={capability} />
          ))
        ) : (
          <span className="text-[10px] text-text-disabled">
            {t('usage.providerCapabilityUnknown')}
          </span>
        )}
      </div>

      <p className="truncate text-xs text-text-secondary">
        {t('usage.providerConfiguredModels', {
          count: group.models.length,
          models: modelNames.join(', '),
        })}
      </p>
      <p className="truncate text-xs text-text-disabled">
        {t('usage.providerConnection', {
          instances: group.instances.join(', ') || '-',
        })}
      </p>
      {/* Status is a PLACEHOLDER: no health observation exists yet, so the row
          says so instead of showing an assumed "healthy". */}
      <p className="text-[10px] text-text-disabled" data-testid="provider-status-placeholder">
        {t('usage.providerStatusNotObserved')}
      </p>
    </li>
  );
}

/**
 * The Model Providers overview: the workspace's configured providers split into
 * Managed API and Private Endpoint, each with its capability tags.
 *
 * It reads `GET /api/v1/models`, which reports provider/instance/model identity
 * and capability only - no credential field is requested or rendered. A provider
 * whose factory is in neither list lands in an explicit `Unclassified` group
 * rather than being assumed to be a cloud API.
 */
export function ModelProviderOverview() {
  const { t } = useTranslation();
  const { data: models, loading } = useFetchConfiguredModels();
  const groups = useMemo(() => groupByProvider(models), [models]);

  const sections = useMemo(
    () =>
      GROUP_ORDER.map((kind) => ({
        kind,
        groups: groups.filter((group) => group.kind === kind),
      })).concat({
        kind: 'unclassified' as ProviderEndpointKind,
        groups: groups.filter((group) => group.kind === 'unclassified'),
      }),
    [groups],
  );

  return (
    <section
      className="shrink-0 border-t border-cable-hairline pt-4"
      data-testid="model-provider-overview"
    >
      <h3 className="pb-2 text-xs font-medium text-text-secondary">
        {t('usage.providerOverviewTitle')}
      </h3>

      {loading && models.length === 0 ? (
        <CardSkeleton />
      ) : groups.length === 0 ? (
        <p className="text-xs text-text-disabled">
          {t('usage.providerOverviewEmpty')}
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {sections.map(({ kind, groups: kindGroups }) =>
            kindGroups.length === 0 ? null : (
              <div key={kind} className="flex flex-col gap-2">
                <div className="flex flex-col">
                  <span
                    className={cn(
                      'text-xs font-medium',
                      kind === 'unclassified'
                        ? 'text-state-warning'
                        : 'text-text-secondary',
                    )}
                  >
                    {t(GROUP_LABEL_KEY[kind])}
                  </span>
                  <span className="text-[10px] text-text-disabled">
                    {t(GROUP_HINT_KEY[kind])}
                  </span>
                </div>
                <ul className="flex flex-col gap-2">
                  {kindGroups.map((group) => (
                    <ProviderRow key={group.providerName} group={group} />
                  ))}
                </ul>
              </div>
            ),
          )}
        </div>
      )}
    </section>
  );
}

export default ModelProviderOverview;
