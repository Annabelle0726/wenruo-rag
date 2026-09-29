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
import {
  classifyProviderEndpoint,
  PRIVATE_ENDPOINT_FACTORIES,
  sortCapabilities,
} from './model-provider-endpoint';

describe('the Managed API / Private Endpoint split', () => {
  it('treats the self-hosted factories as private endpoints', () => {
    expect(classifyProviderEndpoint(LLMFactory.Ollama)).toBe('private');
    expect(classifyProviderEndpoint(LLMFactory.Xinference)).toBe('private');
    expect(classifyProviderEndpoint(LLMFactory.VLLM)).toBe('private');
    expect(
      classifyProviderEndpoint(LLMFactory.OpenAiAPICompatible),
    ).toBe('private');
    expect(PRIVATE_ENDPOINT_FACTORIES).toContain(LLMFactory.LocalAI);
    expect(PRIVATE_ENDPOINT_FACTORIES).toContain(LLMFactory.LMStudio);
  });

  it('treats known cloud factories as managed APIs', () => {
    expect(classifyProviderEndpoint(LLMFactory.DeepSeek)).toBe('managed');
    expect(classifyProviderEndpoint(LLMFactory.OpenAI)).toBe('managed');
    expect(classifyProviderEndpoint(LLMFactory.Gemini)).toBe('managed');
  });

  it('leaves an unknown factory unclassified instead of assuming managed', () => {
    expect(classifyProviderEndpoint('Some-Vendor-Nobody-Listed')).toBe(
      'unclassified',
    );
    expect(classifyProviderEndpoint('')).toBe('unclassified');
    expect(classifyProviderEndpoint(undefined)).toBe('unclassified');
  });
});

describe('capability tags', () => {
  it('orders the four console capabilities first and de-duplicates', () => {
    expect(
      sortCapabilities(['vision', 'chat', 'embedding', 'rerank', 'chat']),
    ).toEqual(['chat', 'embedding', 'rerank', 'vision']);
  });

  it('keeps an unexpected capability visible instead of dropping it', () => {
    expect(sortCapabilities(['ocr', 'chat', 'mystery'])).toEqual([
      'chat',
      'ocr',
      'mystery',
    ]);
  });
});
