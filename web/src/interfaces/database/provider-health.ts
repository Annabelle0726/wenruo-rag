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
 * The provider-health read API's shape, exactly as `GET
 * /tenants/<id>/provider-health/incidents` answers it.
 *
 * Every field here is one the server's allowlist exposes; nothing is inferred
 * client-side. In particular the client never re-derives a severity from an error
 * class, never sums occurrences and never classifies a failure - `severity`,
 * `error_class` and `active_count` are all server decisions.
 */

/** One recorded provider incident. */
export interface IProviderIncident {
  id: string;
  provider_id: string;
  instance_id: string;
  provider_name: string;
  /** An `LLMType` value, e.g. `embedding` / `chat` / `rerank`. Never a fixed list. */
  capability: string;
  error_class: string;
  severity: string;
  occurred_at: string | null;
  last_seen_at: string | null;
  /** How many times this ONE incident was observed - not a count of incidents. */
  occurrence_count: number;
  affected_operation: string;
  /** The server's own safe sentence for this class, already capability-aware. */
  user_safe_message: string;
  /** `active` | `resolved`. */
  state: string;
  resolved_at: string | null;
  resolution_kind: string | null;
}

/** The whole view: the page, plus counts that are exact whatever the page holds. */
export interface IProviderIncidentView {
  incidents: IProviderIncident[];
  /** Incident count for a badge - one incident seen 30 times still counts once. */
  active_count: number;
  recently_resolved_count: number;
  total_in_scope: number;
  limit: number;
  offset: number;
  truncated: boolean;
  lists_incomplete: boolean;
  recently_resolved_window_days: number;
  /** The server's honesty notes; rendered only where they add a fact. */
  not_answered: string[];
}

export const PROVIDER_INCIDENT_STATE = {
  Active: 'active',
  Resolved: 'resolved',
} as const;

export const PROVIDER_INCIDENT_SEVERITY = {
  Error: 'error',
  Warning: 'warning',
} as const;
