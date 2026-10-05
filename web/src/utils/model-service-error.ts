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
 * The refusals a model provider can answer with, and what to say about them.
 *
 * The backend used to hand the provider's own error text to the screen: an
 * upstream JSON body, its request ids and quota metric names, inside one red
 * notification. It now answers with a recognised `error_type`, a sentence a
 * reader can act on, and the raw text kept aside for the log — so the client
 * branches on the type and picks its own wording, which also means the message
 * follows the reader's language rather than the backend's.
 */

export const ModelServiceErrorType = {
  /** The account's quota is used up: waiting will not help. */
  EmbeddingQuotaExhausted: 'EMBEDDING_QUOTA_EXHAUSTED',
  /** Too many requests right now: the same request can succeed shortly. */
  EmbeddingRateLimited: 'EMBEDDING_RATE_LIMITED',
} as const;

export type ModelServiceErrorType =
  (typeof ModelServiceErrorType)[keyof typeof ModelServiceErrorType];

/** One sentence per type, keyed for i18n rather than carried as text. */
const MESSAGE_KEYS: Record<ModelServiceErrorType, string> = {
  [ModelServiceErrorType.EmbeddingQuotaExhausted]:
    'message.embeddingQuotaExhausted',
  [ModelServiceErrorType.EmbeddingRateLimited]: 'message.embeddingRateLimited',
};

/**
 * The recognised type carried by a response body, or null.
 *
 * Takes whatever the API returned — a refusal, an ordinary error, a payload —
 * and answers only for the refusals it understands. Anything else returns null
 * and keeps the handling it had, so this only ever softens what it recognises.
 */
export const modelServiceErrorOf = (body: unknown): ModelServiceErrorType | null => {
  const errorType = (body as { error_type?: unknown } | null | undefined)
    ?.error_type;
  if (typeof errorType !== 'string') return null;

  return errorType in MESSAGE_KEYS
    ? (errorType as ModelServiceErrorType)
    : null;
};

export const modelServiceErrorMessageKey = (type: ModelServiceErrorType) =>
  MESSAGE_KEYS[type];
