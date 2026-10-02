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
  IProviderIncident,
  PROVIDER_INCIDENT_SEVERITY,
  PROVIDER_INCIDENT_STATE,
} from '@/interfaces/database/provider-health';
import { cn } from '@/lib/utils';
import { capabilityLabel, formatIncidentTime } from '@/utils/provider-incident';
import { useTranslation } from 'react-i18next';

/**
 * One recorded incident.
 *
 * What it shows, and what it deliberately does not:
 *
 * - the provider's own name and the capability, as the row's identity, so two
 *   providers are told apart by name and never by an opaque id;
 * - the server's `user_safe_message` as the body - the server classified the
 *   failure and wrote the sentence for it, and this layer does not re-derive it
 *   from `error_class`;
 * - how many times the incident was OBSERVED, and when it was last seen;
 * - the state as a word ("active" / "resolved"), never a green "healthy" light.
 *
 * `instance_id`, `provider_id` and any request metadata are not rendered: they
 * identify a configured credential row and tell a reader nothing they can act on.
 */
function IncidentRow({ incident }: { incident: IProviderIncident }) {
  const { t } = useTranslation();
  const resolved = incident.state === PROVIDER_INCIDENT_STATE.Resolved;
  const lastSeen = formatIncidentTime(incident.last_seen_at);
  const resolvedAt = formatIncidentTime(incident.resolved_at);
  const errored = incident.severity === PROVIDER_INCIDENT_SEVERITY.Error;

  return (
    <li
      className="settings-tile"
      data-testid="provider-incident"
      data-state={incident.state}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="settings-tile-label min-w-0 truncate">
          {incident.provider_name}
          <span className="px-1 text-text-tertiary">·</span>
          {capabilityLabel(incident.capability, t)}
        </span>
        <span className="flex shrink-0 items-center gap-1">
          <span
            className={cn(
              'settings-tag',
              errored ? 'text-state-error' : 'text-state-warning',
            )}
            data-testid="provider-incident-severity"
          >
            {t(
              errored
                ? 'usage.providerIncidentSeverityError'
                : 'usage.providerIncidentSeverityWarning',
            )}
          </span>
          <span
            className={cn(
              'settings-tag',
              resolved ? 'text-text-tertiary' : 'text-text-secondary',
            )}
            data-testid="provider-incident-state"
          >
            {t(
              resolved
                ? 'usage.providerIncidentStateResolved'
                : 'usage.providerIncidentStateActive',
            )}
          </span>
        </span>
      </div>

      <p className="settings-tile-value" data-testid="provider-incident-message">
        {incident.user_safe_message}
      </p>

      <p
        className="settings-tile-hint"
        data-testid="provider-incident-history"
      >
        {t('usage.providerIncidentOccurrences', {
          count: incident.occurrence_count,
        })}
        {lastSeen &&
          ` · ${t('usage.providerIncidentLastSeen', { time: lastSeen })}`}
      </p>

      {/* A resolved incident states WHEN it was resolved. It gets no green
          "provider is healthy" claim - nothing here polls a provider. */}
      {resolved && resolvedAt && (
        <p
          className="settings-tile-hint"
          data-testid="provider-incident-resolved-at"
        >
          {t('usage.providerIncidentResolvedAt', { time: resolvedAt })}
        </p>
      )}
    </li>
  );
}

/**
 * The two sections, in the order the API returns them: what is happening now, then
 * what recently stopped. Active rows carry the state tag; resolved rows are visually
 * quieter but are NOT green, because "resolved" means the observation path saw a
 * success - it does not mean the provider is up.
 */
export function ProviderIncidentList({
  active,
  resolved,
}: {
  active: IProviderIncident[];
  resolved: IProviderIncident[];
}) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col gap-4">
      {active.length > 0 && (
        <section className="settings-section" data-testid="provider-incidents-active">
          <div className="settings-section-head">
            <span className="settings-section-title">
              {t('usage.providerIncidentsActiveHeading')}
            </span>
            <span className="settings-section-hint">
              {t('usage.providerIncidentsActiveHint', { count: active.length })}
            </span>
          </div>
          <ul className="settings-section-body flex flex-col gap-2">
            {active.map((incident) => (
              <IncidentRow key={incident.id} incident={incident} />
            ))}
          </ul>
        </section>
      )}

      {resolved.length > 0 && (
        <section
          className="settings-section"
          data-testid="provider-incidents-resolved"
        >
          <div className="settings-section-head">
            <span className="settings-section-title">
              {t('usage.providerIncidentsResolvedHeading')}
            </span>
            <span className="settings-section-hint">
              {t('usage.providerIncidentsResolvedHint', {
                count: resolved.length,
              })}
            </span>
          </div>
          <ul className="settings-section-body flex flex-col gap-2">
            {resolved.map((incident) => (
              <IncidentRow key={incident.id} incident={incident} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

export default ProviderIncidentList;
