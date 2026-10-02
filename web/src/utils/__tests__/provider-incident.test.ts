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
} from '@/interfaces/database/provider-health';
import {
  activeIncidentsOf,
  capabilityLabel,
  formatIncidentTime,
  notificationSeverityOf,
  providerIncidentNotifications,
  resolvedIncidentsOf,
} from '@/utils/provider-incident';

const incident = (
  overrides: Partial<IProviderIncident> = {},
): IProviderIncident => ({
  id: 'incident-1',
  provider_id: 'provider-1',
  instance_id: 'instance-1',
  provider_name: 'Gemini',
  capability: 'embedding',
  error_class: 'EMBEDDING_QUOTA_EXHAUSTED',
  severity: 'error',
  occurred_at: '2026-03-01 11:40:00',
  last_seen_at: '2026-03-01 11:47:00',
  occurrence_count: 3,
  affected_operation: '',
  user_safe_message: 'AI 对话服务额度已耗尽，请更换 API Key 或等待额度重置后重试。',
  state: 'active',
  resolved_at: null,
  resolution_kind: null,
  ...overrides,
});

const view = (incidents: IProviderIncident[]): IProviderIncidentView => ({
  incidents,
  active_count: incidents.filter((item) => item.state === 'active').length,
  recently_resolved_count: incidents.filter((item) => item.state === 'resolved')
    .length,
  total_in_scope: incidents.length,
  limit: 50,
  offset: 0,
  truncated: false,
  lists_incomplete: false,
  recently_resolved_window_days: 7,
  not_answered: [],
});

// A stand-in for `t` that makes the key it was asked for observable.
const translate = (key: string) => `t:${key}`;
const ROUTE = '/user-setting/usage/provider-health';

describe('a capability label is never invented', () => {
  it('maps the capabilities this console knows', () => {
    expect(capabilityLabel('embedding', translate)).toBe(
      't:setting.capabilityEmbedding',
    );
    expect(capabilityLabel('chat', translate)).toBe('t:setting.capabilityChat');
    expect(capabilityLabel('rerank', translate)).toBe(
      't:setting.capabilityRerank',
    );
  });

  it('falls back to the raw value for an unknown capability', () => {
    // Not a translation key, not a humanised guess, not a blank: the value.
    expect(capabilityLabel('transcribe', translate)).toBe('transcribe');
    expect(capabilityLabel('', translate)).toBe('');
  });
});

describe('a provider incident becomes a notification without inventing anything', () => {
  it('carries the provider, the capability and the server sentence', () => {
    const [notification] = providerIncidentNotifications(
      view([incident()]),
      translate,
      ROUTE,
    );

    expect(notification.id).toBe('provider-incident:incident-1');
    expect(notification.source).toBe('provider_incident');
    expect(notification.titleKey).toBe('notification.providerIncidentTitle');
    expect(notification.params).toEqual({
      provider: 'Gemini',
      capability: 't:setting.capabilityEmbedding',
    });
    // The body is the SERVER's sentence verbatim - no client taxonomy.
    expect(notification.descriptionText).toBe(
      'AI 对话服务额度已耗尽，请更换 API Key 或等待额度重置后重试。',
    );
    expect(notification.metaKey).toBe('notification.providerIncidentMeta');
    expect(notification.metaParams).toEqual({ count: 3 });
    // The time is the last time the incident was SEEN, not "now".
    expect(notification.createdAt).toBe('2026-03-01 11:47:00');
    expect(notification.readAt).toBeNull();
  });

  it('renders no request metadata into a notification', () => {
    const [notification] = providerIncidentNotifications(
      view([incident()]),
      translate,
      ROUTE,
    );
    const rendered = JSON.stringify(notification);

    for (const forbidden of [
      'instance-1',
      'provider-1',
      'EMBEDDING_QUOTA_EXHAUSTED',
      'api_key',
      'raw',
    ]) {
      expect(rendered).not.toContain(forbidden);
    }
  });

  it('carries one entry per INCIDENT, however many occurrences it has', () => {
    const notifications = providerIncidentNotifications(
      view([incident({ occurrence_count: 30 })]),
      translate,
      ROUTE,
    );

    expect(notifications).toHaveLength(1);
    expect(notifications[0].metaParams).toEqual({ count: 30 });
  });

  it('escalates only the server severity it was told about', () => {
    expect(notificationSeverityOf(incident({ severity: 'error' }))).toBe(
      'error',
    );
    expect(notificationSeverityOf(incident({ severity: 'warning' }))).toBe(
      'warning',
    );
    // An unrecognised value is quieter, never louder.
    expect(notificationSeverityOf(incident({ severity: 'critical' }))).toBe(
      'warning',
    );
  });

  it('never turns a resolved incident into a notification', () => {
    const notifications = providerIncidentNotifications(
      view([
        incident({ id: 'active-1' }),
        incident({ id: 'resolved-1', state: 'resolved', resolved_at: '2026-03-01 12:00:00' }),
      ]),
      translate,
      ROUTE,
    );

    expect(notifications.map((item) => item.id)).toEqual([
      'provider-incident:active-1',
    ]);
  });

  it('reports an empty view as an empty list rather than an error', () => {
    expect(providerIncidentNotifications(undefined, translate, ROUTE)).toEqual([]);
    expect(providerIncidentNotifications(view([]), translate, ROUTE)).toEqual([]);
  });
});

describe('the view splits by the state the server reported', () => {
  it('splits active from resolved', () => {
    const data = view([
      incident({ id: 'a' }),
      incident({ id: 'r', state: 'resolved' }),
    ]);

    expect(activeIncidentsOf(data).map((item) => item.id)).toEqual(['a']);
    expect(resolvedIncidentsOf(data).map((item) => item.id)).toEqual(['r']);
    expect(activeIncidentsOf(undefined)).toEqual([]);
  });
});

describe('a server timestamp is displayed as it arrived, or not at all', () => {
  it('formats a server timestamp', () => {
    expect(formatIncidentTime('2026-03-01 11:47:00')).toBe('2026-03-01 11:47');
  });

  it('renders nothing for a missing or unparseable value', () => {
    expect(formatIncidentTime(null)).toBeNull();
    expect(formatIncidentTime(undefined)).toBeNull();
    expect(formatIncidentTime('not a time')).toBeNull();
  });
});
