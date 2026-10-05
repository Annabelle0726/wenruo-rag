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

import { ModelTreeSelect, ModelTypeMap } from '@/components/model-tree-select';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { FieldToModelType } from '@/constants/llm';
import { useTranslate } from '@/hooks/common-hooks';
import {
  useFetchDefaultModelDictionary,
  useSetDefaultModel,
} from '@/hooks/use-llm-request';
import { parseModelValue } from '@/utils/llm-util';
import { CircleQuestionMark } from 'lucide-react';
import { useCallback, useMemo } from 'react';
import { useModelSettingsReadOnly } from '../read-only-context';

interface ModelFieldItemProps {
  id: string;
  label: string;
  value: string;
  tooltip?: string;
  isRequired?: boolean;
  onChange: (id: string, value: string) => void;
}

function ModelFieldItem({
  label,
  value,
  tooltip,
  id,
  isRequired,
  onChange,
}: ModelFieldItemProps) {
  const { t } = useTranslate('setting');
  // Choosing a tenant default model is an admin-only write
  // (`PATCH /models/default`), so a read-only viewer gets a disabled select
  // that still shows the model in force.
  const readOnly = useModelSettingsReadOnly();

  return (
    // One field row: a fixed-width label column, then the control. Six of them
    // stack, so every select in the list starts on the same x — a label that
    // grows in English moves nothing.
    <div className="flex items-center gap-4">
      <label className="settings-field-label w-[9.5rem] shrink-0 leading-snug">
        {isRequired && (
          <span className="settings-required" aria-hidden>
            *
          </span>
        )}
        {label}
        {tooltip && (
          <Tooltip>
            <TooltipContent>{tooltip}</TooltipContent>
            <TooltipTrigger>
              <CircleQuestionMark
                size={12}
                className="ms-1 inline-block align-[-1px] text-content-tertiary"
              />
            </TooltipTrigger>
          </Tooltip>
        )}
      </label>
      <div className="min-w-0 flex-1">
        <ModelTreeSelect
          modelTypes={ModelTypeMap[id as keyof typeof ModelTypeMap] ?? ['chat']}
          value={value}
          onChange={(val) => onChange(id, val)}
          placeholder={t('selectModelPlaceholder')}
          showSearch
          disabled={readOnly}
          allowClear={id !== 'llm_id'}
          // Glass well with the shared hairline: the accent ring on focus comes
          // with the class, so the select matches the search fields.
          className="ceramic-field h-10 w-full"
        />
      </div>
    </div>
  );
}

function SystemSetting() {
  const { t } = useTranslate('setting');
  const defaultModelDictionary = useFetchDefaultModelDictionary();
  const { setDefaultModel } = useSetDefaultModel();

  const handleFieldChange = useCallback(
    async (field: string, value: string) => {
      const modelType = FieldToModelType[field];
      if (!modelType) return;
      const parsed = parseModelValue(value);
      if (parsed) {
        await setDefaultModel({ ...parsed, model_type: modelType });
      } else {
        await setDefaultModel({ model_id: value, model_type: modelType });
      }
    },
    [setDefaultModel],
  );

  const llmList = useMemo(() => {
    return [
      {
        id: 'llm_id',
        label: t('chatModel'),
        isRequired: true,
        value: defaultModelDictionary.llm_id ?? '',
        tooltip: t('chatModelTip'),
      },
      {
        id: 'embd_id',
        label: t('embeddingModel'),
        value: defaultModelDictionary.embd_id ?? '',
        tooltip: t('embeddingModelTip'),
      },
      {
        id: 'img2txt_id',
        label: t('img2txtModel'),
        value: defaultModelDictionary.img2txt_id ?? '',
        tooltip: t('img2txtModelTip'),
      },
      {
        id: 'asr_id',
        label: t('sequence2txtModel'),
        value: defaultModelDictionary.asr_id ?? '',
        tooltip: t('sequence2txtModelTip'),
      },
      {
        id: 'rerank_id',
        label: t('rerankModel'),
        value: defaultModelDictionary.rerank_id ?? '',
        tooltip: t('rerankModelTip'),
      },
      {
        id: 'tts_id',
        label: t('ttsModel'),
        value: defaultModelDictionary.tts_id ?? '',
        tooltip: t('ttsModelTip'),
      },
    ];
  }, [defaultModelDictionary, t]);

  return (
    // The same header bar and gutters the provider destination uses, so switching
    // between "default models" and a provider does not move the title or the
    // content's left edge by 20px.
    <article className="flex w-full flex-col">
      <header className="flex min-w-0 flex-col gap-0.5 border-b border-cable-hairline px-5 py-3">
        <h2 className="settings-title truncate">
          {t('systemModelSettings')}
        </h2>
        <p className="settings-description truncate">
          {t('systemModelDescription')}
        </p>
      </header>

      {/* The panel's own scroll container does the scrolling; a second, capped
          scroller here produced two nested scrollbars for one list. */}
      <div className="settings-body">
        {/* One hairline frame around the six defaults, a hairline between them:
            the list reads as one object and the required field keeps the only
            brand-coloured mark on the page. */}
        <section className="settings-section divide-y divide-cable-hairline">
          {llmList.map((item) => (
            <div key={item.id} className="px-4 py-3.5">
              <ModelFieldItem {...item} onChange={handleFieldChange} />
            </div>
          ))}
        </section>
      </div>
    </article>
  );
}

export default SystemSetting;
