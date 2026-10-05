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
  IProviderIncidentView,
  PROVIDER_INCIDENT_SEVERITY,
  PROVIDER_INCIDENT_STATE,
} from '@/interfaces/database/provider-health';
import {
  IWorkspaceNotification,
  NotificationSeverity,
} from '@/interfaces/notification';
import dayjs from 'dayjs';

/**
 * The label for a capability, or the raw value when it is not one we know.
 *
 * The fallback is the value itself - never a translation key, never a humanised
 * guess. A capability is an open set (`LLMType` today, something else tomorrow),
 * and a provider this console has never heard of must still render: it gets its
 * own name, not a missing-key echo and not a silently blank cell.
 */
const CAPABILITY_LABEL_KEYS: Record<string, string> = {
  embedding: 'setting.capabilityEmbedding',
  chat: 'setting.capabilityChat',
  rerank: 'setting.capabilityRerank',
  vision: 'setting.capabilityVlm',
  asr: 'setting.capabilityAsr',
  tts: 'setting.capabilityTts',
  ocr: 'setting.capabilityOcr',
};

export const capabilityLabelKey = (capability: string): string | undefined =>
  CAPABILITY_LABEL_KEYS[capability];

export const capabilityLabel = (
  capability: string,
  translate: (key: string) => string,
): string => {
  const key = capabilityLabelKey(capability);
  return key ? translate(key) : capability;
};

/**
 * The severity a notification carries.
 *
 * Only the server's own `error` is escalated; anything else - `warning`, a value
 * this release does not know - is presented as a warning rather than as an error.
 * The opposite default would turn an unrecognised string into a red badge.
 */
export const notificationSeverityOf = (incident: IProviderIncident): NotificationSeverity =>
  incident.severity === PROVIDER_INCIDENT_SEVERITY.Error ? 'error' : 'warning';

/**
 * A provider incident as a notification.
 *
 * Only ACTIVE incidents become entries: a resolved incident is a fact the Provider
 * Health page reports, not something to keep ringing a bell about. The id is
 * derived from the INCIDENT, so the store's own replacement rule applies - the
 * entry exists exactly while the incident is active, and closing the drawer, marking
 * it read or writing `readAt` changes nothing about the incident.
 *
 * The body is the server's `user_safe_message`: the sentence is the server's own
 * capability-aware wording for the classified failure, and re-deriving it here from
 * `error_class` would be a second taxonomy on the client.
 *
 * `route` is supplied by the caller rather than imported here: this module stays a
 * pure projection of server facts, with no dependency on the router.
 */
export const providerIncidentNotifications = (
  view: IProviderIncidentView | undefined,
  translate: (key: string) => string,
  route?: string,
): IWorkspaceNotification[] =>
  (view?.incidents ?? [])
    .filter((incident) => incident.state === PROVIDER_INCIDENT_STATE.Active)
    .map((incident) => ({
      id: `provider-incident:${incident.id}`,
      category:
        notificationSeverityOf(incident) === 'error'
          ? ('PROVIDER_UNAVAILABLE' as const)
          : ('PROVIDER_DEGRADED' as const),
      severity: notificationSeverityOf(incident),
      titleKey: 'notification.providerIncidentTitle',
      params: {
        provider: incident.provider_name,
        capability: capabilityLabel(incident.capability, translate),
      },
      descriptionText: incident.user_safe_message,
      metaKey: 'notification.providerIncidentMeta',
      metaParams: { count: incident.occurrence_count },
      // The last time it was SEEN, not an invented "now".
      createdAt: incident.last_seen_at ?? undefined,
      readAt: null,
      route,
      source: 'provider_incident' as const,
    }));

/** A server timestamp for display, or null when there is none to show. */
export const formatIncidentTime = (value: string | null | undefined): string | null => {
  if (!value) {
    return null;
  }
  const parsed = dayjs(value.replace(' ', 'T'));
  return parsed.isValid() ? parsed.format('YYYY-MM-DD HH:mm') : null;
};

export const activeIncidentsOf = (view: IProviderIncidentView | undefined) =>
  (view?.incidents ?? []).filter(
    (incident) => incident.state === PROVIDER_INCIDENT_STATE.Active,
  );

export const resolvedIncidentsOf = (view: IProviderIncidentView | undefined) =>
  (view?.incidents ?? []).filter(
    (incident) => incident.state === PROVIDER_INCIDENT_STATE.Resolved,
  );
