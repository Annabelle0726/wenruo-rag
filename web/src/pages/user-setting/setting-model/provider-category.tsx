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
import { Button } from '@/components/ui/button';
import {
  CAPABILITY_LABEL_KEY,
  classifyProviderEndpoint,
  ProviderEndpointKind,
  sortCapabilities,
} from '@/constants/model-provider-endpoint';
import { useFetchConfiguredModels } from '@/hooks/use-model-provider-request';
import { IAddedModel } from '@/interfaces/database/llm';
import { cn } from '@/lib/utils';
import { ChevronRight } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation } from 'react-router';
import { ComingDataPanel } from '../usage-operations/components/coming-data-panel';
import { ProfileSettingWrapperCard } from '../components/user-setting-header';

interface IProviderGroup {
  providerName: string;
  kind: ProviderEndpointKind;
  instances: string[];
  models: IAddedModel[];
  capabilities: string[];
}

const KIND_TITLE_KEY: Record<ProviderEndpointKind, string> = {
  managed: 'setting.modelManagedApi',
  private: 'setting.modelPrivateEndpoint',
  unclassified: 'setting.modelUnclassified',
};

const KIND_HINT_KEY: Record<ProviderEndpointKind, string> = {
  managed: 'usage.providerGroupManagedHint',
  private: 'usage.providerGroupPrivateHint',
  unclassified: 'usage.providerGroupUnclassifiedHint',
};

/**
 * Groups the workspace's configured models by provider and classifies each
 * provider's endpoint type.
 *
 * The input is the provider's CONFIGURED identity (`provider_name`, the factory
 * the workspace actually configured), not a label a reader typed, so the split is
 * derived from authoritative configuration. A stronger signal exists - a custom
 * `base_url` marks a self-hosted gateway explicitly - but it is only readable from
 * the provider-instance endpoint, whose payload also carries the credential field.
 * Reading it to sharpen a cosmetic grouping is not worth pulling a key into the
 * browser, so the classification stays on the factory identity and anything it
 * cannot place is reported as Unclassified rather than guessed.
 */
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
    <Badge
      className="rounded-[2px] px-1.5 py-0 text-[10px] font-normal leading-4"
      data-testid="provider-capability"
    >
      {/* An unmapped capability keeps its RAW name rather than disappearing. */}
      {labelKey ? t(labelKey) : capability}
    </Badge>
  );
}

/**
 * One provider, collapsed to a single row until a reader opens it.
 *
 * A collapsed card carries everything needed to choose: the provider, its type,
 * its capabilities and how many models it serves. The connection detail and the
 * model list unfold underneath, which is what keeps a section with a dozen
 * providers readable.
 */
function ProviderCard({ group }: { group: IProviderGroup }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const modelNames = group.models.map((model) => model.name).filter(Boolean);

  return (
    <li
      className="ceramic-relief rounded-[2px]"
      data-testid={`provider-row-${group.providerName}`}
    >
      <div className="flex items-center gap-2 p-2.5">
        <Button
          variant="ghost"
          size="icon"
          className="size-6 shrink-0 p-0 text-text-secondary hover:text-text-primary"
          aria-expanded={open}
          aria-label={t('usage.providerToggleDetails', {
            provider: group.providerName || t('usage.providerNameUnknown'),
          })}
          onClick={() => setOpen((previous) => !previous)}
          data-testid={`provider-toggle-${group.providerName}`}
        >
          <ChevronRight
            className={cn('size-3.5 transition-transform', open && 'rotate-90')}
          />
        </Button>

        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm text-text-primary">
              {group.providerName || t('usage.providerNameUnknown')}
            </span>
            <Badge className="shrink-0 rounded-[2px] px-1.5 py-0 text-[10px] font-normal leading-4">
              {t(KIND_TITLE_KEY[group.kind])}
            </Badge>
          </div>

          <div className="flex flex-wrap items-center gap-1">
            <span className="text-[11px] text-text-secondary">
              {t('setting.capabilities')}
            </span>
            {group.capabilities.length > 0 ? (
              group.capabilities.map((capability) => (
                <CapabilityTag key={capability} capability={capability} />
              ))
            ) : (
              <span className="text-[11px] text-text-disabled">
                {t('usage.providerCapabilityUnknown')}
              </span>
            )}
          </div>
        </div>

        <span className="shrink-0 text-[11px] text-text-disabled">
          {t('usage.providerModelCount', { count: group.models.length })}
        </span>
      </div>

      {open && (
        <div className="flex flex-col gap-1.5 border-t border-cable-hairline px-3 py-2">
          <p className="text-xs text-text-secondary">
            {t('usage.providerConfiguredModels', {
              count: group.models.length,
              models: modelNames.join(', ') || '-',
            })}
          </p>
          <p className="text-xs text-text-disabled">
            {t('usage.providerConnection', {
              instances: group.instances.join(', ') || '-',
            })}
          </p>
          {/* A PLACEHOLDER, never a status: no health observation exists yet, so
              the row says so instead of showing an assumed "healthy". */}
          <p
            className="text-[11px] text-text-disabled"
            data-testid="provider-status-placeholder"
          >
            {t('usage.providerStatusNotObserved')}
          </p>
        </div>
      )}
    </li>
  );
}

const KIND_BY_SEGMENT: Record<string, ProviderEndpointKind> = {
  managed: 'managed',
  private: 'private',
  unclassified: 'unclassified',
};

/**
 * One Model Providers destination: the providers of a single category.
 *
 * The category is a real route (`/model/managed`, `/model/private`,
 * `/model/unclassified`), so the rail highlights it, it can be linked to, and the
 * category a reader is looking at and the entry they selected are the same fact.
 * The existing management page stays at `/model` and is untouched.
 */
function ProviderCategory() {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const { data: models, loading } = useFetchConfiguredModels();

  const kind = useMemo(() => {
    const segment = pathname.split('/').filter(Boolean).pop() ?? '';
    return KIND_BY_SEGMENT[segment] ?? 'managed';
  }, [pathname]);

  const groups = useMemo(
    () =>
      groupByProvider(models).filter((group) => group.kind === kind),
    [kind, models],
  );

  return (
    <ProfileSettingWrapperCard
      header={
        <header className="flex flex-col gap-1">
          <h2 className="text-2xl font-medium text-text-primary">
            {t(KIND_TITLE_KEY[kind])}
          </h2>
          <p className="text-xs text-text-secondary">{t(KIND_HINT_KEY[kind])}</p>
        </header>
      }
    >
      <div className="flex flex-col gap-3 p-4">
        {loading && models.length === 0 ? (
          <CardSkeleton />
        ) : groups.length === 0 ? (
          <ComingDataPanel
            testId={`provider-category-empty-${kind}`}
            tone="unavailable"
            titleKey="usage.providerCategoryEmptyTitle"
            descriptionKey="usage.providerCategoryEmptyDescription"
          />
        ) : (
          <ul
            className="flex flex-col gap-2"
            data-testid={`provider-category-${kind}`}
          >
            {groups.map((group) => (
              <ProviderCard key={group.providerName} group={group} />
            ))}
          </ul>
        )}

        {/* What this category does NOT claim, stated where a reader would look for
            a health or balance column. */}
        <p className="text-xs text-text-disabled">
          {t('usage.providerCategoryCaveat')}
        </p>
      </div>
    </ProfileSettingWrapperCard>
  );
}

export default ProviderCategory;
