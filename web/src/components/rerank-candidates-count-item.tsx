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

import { FormLayout } from '@/constants/form';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';
import { SliderInputFormField } from './slider-input-form-field';

// The candidate pool only has to clear what the result page asks for
// (`page * page_size`, capped by this same value in the page-size selector), so
// the floor sits at a handful rather than at the old 64 — a search page shows a
// few references and reranking further candidates only adds latency.
export const rerankCandidatesCountSchema = {
  rerank_candidates_count: z.number().int().min(10).max(256),
};

interface RerankCandidatesCountFormFieldProps {
  defaultValue?: number;
  name?: string;
}

export function RerankCandidatesCountFormField({
  defaultValue = 30,
  name = 'rerank_candidates_count',
}: RerankCandidatesCountFormFieldProps) {
  const { t } = useTranslation();

  return (
    <SliderInputFormField
      name={name}
      label={t('chat.rerankCandidatesCount')}
      tooltip={t('chat.rerankCandidatesCountTip')}
      min={10}
      max={256}
      defaultValue={defaultValue}
      layout={FormLayout.Vertical}
    ></SliderInputFormField>
  );
}
