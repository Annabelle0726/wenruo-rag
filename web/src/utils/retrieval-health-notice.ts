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

import { ExternalToast, toast } from 'sonner';

import { IReference } from '@/interfaces/database/chat';
import i18n from '@/locales/config';

/**
 * User disclosure for a degraded retrieval (P0-6 / C1-C6).
 *
 * The backend already ships `retrieval_health` beside the existing reference
 * keys, so this module only maps that signal onto a notice. It is the single
 * place in the product that decides whether a user is told anything about
 * retrieval health.
 *
 * Privacy by construction: the only strings that can reach the screen are the
 * two localized constants below. `overall`, `degradation_reason` and
 * `evidence_completeness` are read as lookup keys and are never rendered,
 * interpolated, logged or attached to an error - so no API key, endpoint,
 * stack trace or provider payload has a path to the UI through this module.
 */

/** The only two disclosures that exist. An unrecognised state stays silent. */
export type RetrievalNoticeKind = 'degraded' | 'failed';

/**
 * Structural view of the additive DTO. Every field is `unknown` on purpose: it is validated, not
 * trusted.
 *
 * Only `overall` selects a notice. `degradation_reason` and `evidence_completeness` are part of the
 * contract but deliberately do NOT choose any wording: the retrieval layer cannot prove *which* leg
 * survived, so any sentence naming a mechanism (for example "fell back to text search") would state
 * something never observed. Measured against the deployed code, an embedding failure aborts the route
 * before the store round trip (`store_round_trips = 0`), so lexical search never runs in that route -
 * there is no general text-search fallback to promise.
 */
export type RetrievalHealthLike = {
  overall?: unknown;
  evidence_completeness?: unknown;
  degradation_reason?: unknown;
};

const DEGRADED: RetrievalNoticeKind = 'degraded';
const FAILED: RetrievalNoticeKind = 'failed';

const OVERALL_FULL = 'full';
const OVERALL_DEGRADED = 'degraded';
const OVERALL_FAILED = 'failed';

const NOTICE_TEXT_KEY: Record<RetrievalNoticeKind, string> = {
  degraded: 'message.retrievalNotice.degraded',
  failed: 'message.retrievalNotice.failed',
};

/** A failure is reported as an error; a degradation never is - it is information, not an alarm. */
const NOTICE_IS_ERROR: Record<RetrievalNoticeKind, boolean> = {
  degraded: false,
  failed: true,
};

const NOTICE_DURATION_MS = 4000;
const NOTICE_POSITION: ExternalToast['position'] = 'top-center';

/**
 * Anti-storm window. Five sub-routes cannot stack notices because the backend
 * already aggregates them into ONE `retrieval_health`; this window additionally
 * keeps concurrent or rapidly repeated answers from stacking the same kind.
 */
const SAME_KIND_COOLDOWN_MS = 10_000;

/** Bounded so a long session cannot grow the per-answer guard without limit. */
const ANSWER_GUARD_LIMIT = 200;

const readString = (value: unknown): string | undefined =>
  typeof value === 'string' ? value : undefined;

/**
 * Maps the DTO onto a disclosure, or `null` for "say nothing".
 *
 * C1 `full`            -> null (silent)
 * C2 missing/malformed -> null (fail-safe: never invent a state)
 * C3 `degraded`        -> one honest notice, whatever the reason
 * C4 `failed`          -> explicit retrieval-failure notice
 * anything else        -> null (never render an unrecognised value)
 *
 * `degradation_reason` deliberately does not select wording. The reason is only
 * ever a lookup key, and no sentence here claims a mechanism the deployment has
 * not proven; a degraded answer is reported as degraded, nothing more.
 */
export const noticeForRetrievalHealth = (
  health?: RetrievalHealthLike | null,
): RetrievalNoticeKind | null => {
  if (!health || typeof health !== 'object') return null;

  const overall = readString(health.overall);
  if (overall === OVERALL_FULL) return null;
  if (overall === OVERALL_FAILED) return FAILED;
  if (overall === OVERALL_DEGRADED) return DEGRADED;
  return null;
};

/** `answerKey -> kinds already disclosed for that answer`. */
const disclosedPerAnswer = new Map<string, Set<RetrievalNoticeKind>>();
const lastShownAt = new Map<RetrievalNoticeKind, number>();

const rememberAnswer = (answerKey: string, kind: RetrievalNoticeKind) => {
  const kinds = disclosedPerAnswer.get(answerKey) ?? new Set<RetrievalNoticeKind>();
  kinds.add(kind);
  // Re-inserting moves the key to the end so the eviction below drops the oldest.
  disclosedPerAnswer.delete(answerKey);
  disclosedPerAnswer.set(answerKey, kinds);

  while (disclosedPerAnswer.size > ANSWER_GUARD_LIMIT) {
    const oldest = disclosedPerAnswer.keys().next().value;
    if (oldest === undefined) break;
    disclosedPerAnswer.delete(oldest);
  }
};

const showNotice = (kind: RetrievalNoticeKind) => {
  const text = i18n.t(NOTICE_TEXT_KEY[kind]);
  const options: ExternalToast = {
    // A stable id makes an identical notice supersede its predecessor instead of
    // stacking a second card, whatever the caller does.
    id: `retrieval-notice-${kind}`,
    duration: NOTICE_DURATION_MS,
    position: NOTICE_POSITION,
  };

  if (NOTICE_IS_ERROR[kind]) {
    toast.error(text, options);
    return;
  }
  toast.warning(text, options);
};

/**
 * The only function that may put a retrieval notice on screen.
 *
 * @param reference the response `reference` object (additive field read only)
 * @param answerKey optional stable identity of the answer being rendered. When
 *   supplied, one answer is disclosed at most once per kind - which is what the
 *   handlers in `logic-hooks` need, because they run from an effect and can fire
 *   more than once for the same answer.
 * @returns the kind shown, or `null` when nothing was shown.
 */
export const notifyRetrievalHealth = (
  reference?: IReference | null,
  answerKey?: string,
): RetrievalNoticeKind | null => {
  const kind = noticeForRetrievalHealth(reference?.retrieval_health);
  if (!kind) return null;

  if (answerKey) {
    if (disclosedPerAnswer.get(answerKey)?.has(kind)) return null;
    rememberAnswer(answerKey, kind);
  }

  const now = Date.now();
  const previous = lastShownAt.get(kind);
  if (previous !== undefined && now - previous < SAME_KIND_COOLDOWN_MS) {
    return null;
  }
  lastShownAt.set(kind, now);

  showNotice(kind);
  return kind;
};

/**
 * Clears the dedup memory. For tests only - production never needs to forget
 * that a user has already been told.
 */
export const resetRetrievalNoticeDedup = () => {
  disclosedPerAnswer.clear();
  lastShownAt.clear();
};
