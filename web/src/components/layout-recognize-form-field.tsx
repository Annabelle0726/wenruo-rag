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

import { useTranslate } from '@/hooks/common-hooks';
import { useFetchAllAddedModels } from '@/hooks/use-llm-request';
import { cn } from '@/lib/utils';
import { camelCase } from 'lodash';
import { ReactNode, useCallback, useMemo } from 'react';
import { useFormContext } from 'react-hook-form';
import { MinerUOptionsFormField } from './mineru-options-form-field';
import { buildModelTree } from './model-tree-select';
import { PaddleOCROptionsFormField } from './paddleocr-options-form-field';
import { TreeSelect, TreeSelectNode } from './tree-select';
import { Button } from './ui/button';
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from './ui/form';

export const enum ParseDocumentType {
  DeepDOC = 'DeepDOC',
  PlainText = 'Plain Text',
  Docling = 'Docling',
  OpenDataLoader = 'OpenDataLoader',
  TCADPParser = 'TCADP Parser',
  MonkeyOCRv2 = 'MonkeyOCRv2',
}

export function LayoutRecognizeFormField({
  name = 'parser_config.layout_recognize',
  horizontal = true,
  optionsWithoutLLM,
  label,
  showMineruOptions = true,
  showPaddleocrOptions = true,
  testId,
  ownerTenantId,
  hintVariant = 'link',
}: {
  name?: string;
  horizontal?: boolean;
  optionsWithoutLLM?: { value: string; label: string }[];
  label?: ReactNode;
  showMineruOptions?: boolean;
  showPaddleocrOptions?: boolean;
  testId?: string;
  ownerTenantId?: string;
  /**
   * How the standard/scanned guidance under the dropdown is dressed. `'link'` is
   * the long-standing presentation - a green link followed by the tip, on the
   * field's own line. `'quiet'` puts both inside one hairline callout with a 5%
   * accent wash, so it reads as advice underneath a field rather than as a second
   * action competing with it: same words, same one-click preset, lower weight. It
   * is never an alert - nothing here is wrong.
   */
  hintVariant?: 'link' | 'quiet';
}) {
  const form = useFormContext();

  const { t } = useTranslate('knowledgeDetails');

  /**
   * The guidance for standard/scanned PDFs, as a one-click value instead of
   * prose the reader has to map onto the dropdown: DeepDOC is the right default
   * for born-digital PDFs (it keeps table structure and page positions), but on
   * a scanned standard it was measured to merge adjacent lines and flatten a
   * wide table row — the failure that made a coal-industry standard report its
   * own 表3 as missing.
   */
  const handleUsePlainTextPreset = useCallback(() => {
    form.setValue(name, ParseDocumentType.PlainText, {
      shouldDirty: true,
      shouldValidate: true,
    });
  }, [form, name]);
  const {
    data: allAddedModels,
    isFetched: modelsFetched,
    isError: modelsError,
  } = useFetchAllAddedModels(undefined, ownerTenantId);

  const treeData = useMemo(() => {
    const list = optionsWithoutLLM
      ? optionsWithoutLLM
      : [
          ParseDocumentType.DeepDOC,
          ParseDocumentType.PlainText,
          ParseDocumentType.Docling,
          ParseDocumentType.OpenDataLoader,
          ParseDocumentType.TCADPParser,
          ParseDocumentType.MonkeyOCRv2,
        ].map((x) => ({
          label: x === ParseDocumentType.PlainText ? t(camelCase(x)) : x,
          value: x,
        }));

    const prependNodes: TreeSelectNode[] = list.map((x) => ({
      id: x.value,
      title: x.label,
    }));

    const modelTree = buildModelTree(
      allAddedModels,
      ['image2text', 'ocr', 'vision'],
      (node) => (
        <div className="flex justify-between items-center gap-2 w-full">
          <span className="flex items-center gap-1.5 truncate">
            {node.label}
          </span>
          <span className="text-state-error text-sm flex-shrink-0">
            Experimental
          </span>
        </div>
      ),
    );

    return [...prependNodes, ...modelTree];
  }, [allAddedModels, optionsWithoutLLM, t]);

  return (
    <FormField
      control={form.control}
      name={name}
      render={({ field }) => {
        return (
          <>
            <FormItem className={'items-center space-y-0 '}>
              <div
                className={cn('flex', {
                  'flex-col ': !horizontal,
                  'items-center': horizontal,
                })}
              >
                <FormLabel
                  tooltip={t('layoutRecognizeTip')}
                  className={cn('text-sm text-text-secondary whitespace-wrap', {
                    ['w-1/4']: horizontal,
                  })}
                >
                  {label || t('layoutRecognize')}
                </FormLabel>
                <div className={horizontal ? 'w-3/4' : 'w-full'}>
                  <FormControl>
                    <TreeSelect
                      {...field}
                      data={treeData}
                      testId={testId}
                      showSearch
                      defaultExpandAll
                      loading={!modelsFetched || modelsError}
                      renderSelected={(node) => {
                        if (!node) return null;
                        return node.label ?? node.title;
                      }}
                    />
                  </FormControl>
                </div>
              </div>
              <div className="flex pt-1">
                <div className={horizontal ? 'w-1/4' : 'w-full'}></div>
                <FormMessage />
              </div>
              <div
                className={cn(
                  'flex flex-wrap items-center gap-x-2 gap-y-1 text-xs',
                  {
                    'pl-[25%] pt-1': horizontal,
                    'rounded-md border border-accent-primary/20 bg-accent-primary/5 px-2.5 py-1.5 text-text-secondary':
                      hintVariant === 'quiet',
                  },
                )}
              >
                <Button
                  type="button"
                  variant="link"
                  size="sm"
                  className={cn('h-auto p-0 text-xs text-accent-primary', {
                    'font-normal no-underline hover:underline':
                      hintVariant === 'quiet',
                  })}
                  onClick={handleUsePlainTextPreset}
                >
                  {t('plainTextPreset')}
                </Button>
                <span className="text-text-secondary">
                  {t('plainTextPresetTip')}
                </span>
              </div>
            </FormItem>
            {showMineruOptions && <MinerUOptionsFormField />}
            {showPaddleocrOptions && <PaddleOCROptionsFormField />}
          </>
        );
      }}
    />
  );
}
