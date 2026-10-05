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

import { LLMFactory } from '@/constants/llm';

/**
 * How a configured model provider is REACHED, which is the only thing the
 * Managed API / Private Endpoint split claims.
 *
 * It is a classification of the provider's own identity - never a health, cost
 * or availability claim, and never a statement about where data is stored. A
 * provider outside both lists is reported as `unclassified` rather than being
 * silently folded into "managed": guessing would mislabel a self-hosted gateway
 * as a cloud API.
 */
export type ProviderEndpointKind = 'managed' | 'private' | 'unclassified';

/**
 * The factories the product treats as a PRIVATE ENDPOINT.
 *
 * These are the self-hosted / local-runtime / OpenAI-compatible-gateway
 * factories the console already offers: a private endpoint is reached at an
 * address the operator runs, so it exposes no provider account, no provider
 * balance and no provider-side quota - which is why the UI must never render one
 * for them.
 */
export const PRIVATE_ENDPOINT_FACTORIES: readonly string[] = [
  LLMFactory.Ollama,
  LLMFactory.Xinference,
  LLMFactory.LocalAI,
  LLMFactory.LMStudio,
  LLMFactory.OpenAiAPICompatible,
  LLMFactory.VLLM,
  LLMFactory.GPUStack,
  LLMFactory.Builtin,
  LLMFactory.FastEmbed,
  LLMFactory.PaddleOCRLocal,
];

const KNOWN_FACTORIES: ReadonlySet<string> = new Set(
  Object.values(LLMFactory) as string[],
);

const PRIVATE_FACTORIES: ReadonlySet<string> = new Set(
  PRIVATE_ENDPOINT_FACTORIES,
);

export const classifyProviderEndpoint = (
  providerName: string | undefined,
): ProviderEndpointKind => {
  if (!providerName) {
    return 'unclassified';
  }
  if (PRIVATE_FACTORIES.has(providerName)) {
    return 'private';
  }
  return KNOWN_FACTORIES.has(providerName) ? 'managed' : 'unclassified';
};

/**
 * Capability tags, in the order the console shows them.
 *
 * The server reports a model's type bitmask as lowercase names; `vision` is the
 * VLM capability. A type outside this list keeps its raw name rather than being
 * dropped, so an unexpected capability is visible instead of invisible.
 */
export const CAPABILITY_ORDER: readonly string[] = [
  'chat',
  'embedding',
  'rerank',
  'vision',
  'asr',
  'tts',
  'ocr',
];

export const CAPABILITY_LABEL_KEY: Record<string, string> = {
  chat: 'setting.capabilityChat',
  embedding: 'setting.capabilityEmbedding',
  rerank: 'setting.capabilityRerank',
  vision: 'setting.capabilityVlm',
  asr: 'setting.capabilityAsr',
  tts: 'setting.capabilityTts',
  ocr: 'setting.capabilityOcr',
};

/** Sorts capability tags into the console's order, keeping unknown ones last. */
export const sortCapabilities = (types: readonly string[]): string[] => {
  const unique = Array.from(new Set(types.filter(Boolean)));
  return unique.sort((a, b) => {
    const indexA = CAPABILITY_ORDER.indexOf(a);
    const indexB = CAPABILITY_ORDER.indexOf(b);
    if (indexA === -1 && indexB === -1) {
      return a.localeCompare(b);
    }
    if (indexA === -1) {
      return 1;
    }
    if (indexB === -1) {
      return -1;
    }
    return indexA - indexB;
  });
};
