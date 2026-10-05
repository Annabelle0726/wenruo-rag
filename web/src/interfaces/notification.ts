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
 * The notification shell's typed model.
 *
 * U2 ships the SHELL only: the icon, the unread badge, the drawer, the read
 * state and this type. It deliberately does not invent events. Exactly one real
 * source exists today - a workspace invitation the caller has not answered yet,
 * which the header already used to decorate the bell - so that is the only kind
 * that is ever constructed. The remaining categories are declared because the
 * drawer renders by category, and a category with no backend source must produce
 * NOTHING rather than a placeholder notification.
 */
export type NotificationCategory =
  | 'USAGE_WARNING'
  | 'USAGE_DENIED'
  | 'PROVIDER_DEGRADED'
  | 'PROVIDER_UNAVAILABLE'
  | 'RETRIEVAL_DEGRADED'
  | 'SYSTEM_WARNING';

export type NotificationSeverity = 'info' | 'warning' | 'error';

/**
 * Where a notification came from. Recorded so a reader can tell an OBSERVED fact
 * from anything else, and so a future source is added explicitly rather than by
 * broadening an existing one.
 *
 * - `workspace_invitation`: an invitation the caller has not answered yet.
 * - `provider_incident`: an ACTIVE provider incident the read API reports. The
 *   entry exists while the incident is active and disappears when the server
 *   resolves it - the bell never decides that a provider recovered.
 */
export type NotificationSource = 'workspace_invitation' | 'provider_incident';

export interface IWorkspaceNotification {
  id: string;
  category: NotificationCategory;
  severity: NotificationSeverity;
  /** Translation key, resolved by the caller: the model stores keys, not copy. */
  titleKey: string;
  descriptionKey?: string;
  /**
   * Server-authored body copy, used INSTEAD of `descriptionKey`.
   *
   * A provider incident's text is the server's own safe sentence for the
   * classified failure, already capability-aware. Re-deriving it here from
   * `error_class` would be a second failure taxonomy on the client, which is
   * exactly what the classification contract forbids, so the sentence is carried
   * through verbatim. A source that has no server copy keeps using a key.
   */
  descriptionText?: string;
  /** Interpolation values for the keys above. */
  params?: Record<string, string | number>;
  /**
   * The supplementary line under the body, as a translation key (e.g. "occurred
   * {{count}} times"). Optional: a source with nothing to add renders no line.
   */
  metaKey?: string;
  /** Interpolation values for `metaKey` alone, so a count cannot leak into copy
   * that does not expect one. */
  metaParams?: Record<string, string | number>;
  /**
   * ISO timestamp of the underlying record. Optional because a source that does
   * not report a time must not be decorated with an invented one - the drawer
   * then renders the entry without a relative time.
   */
  createdAt?: string;
  /** Local read state; `null` until the reader opens it. Never persisted. */
  readAt: string | null;
  /** Where "open" navigates. Absent means the notification has no destination. */
  route?: string;
  source: NotificationSource;
}
