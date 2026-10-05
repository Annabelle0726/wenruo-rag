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
import { cn } from '@/lib/utils';
import { useFormContext } from 'react-hook-form';
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from './ui/form';
import { Switch } from './ui/switch';

export function ExcelToHtmlFormField({
  switchPlacement = 'end',
}: {
  /**
   * `'end'` is the long-standing row (the switch at the far end of the control
   * column, which the parsing dialogs keep). `'control'` puts it at the start of
   * that column, in line with every other control on the parser page, so the switch
   * reads as part of its own field instead of a toggle at the panel's edge.
   */
  switchPlacement?: 'end' | 'control';
} = {}) {
  const form = useFormContext();
  const { t } = useTranslate('knowledgeDetails');

  return (
    <FormField
      control={form.control}
      name="parser_config.html4excel"
      render={({ field }) => {
        if (typeof field.value === 'undefined') {
          // default value set
          form.setValue('parser_config.html4excel', false);
        }

        return (
          <FormItem defaultChecked={false} className=" items-center space-y-0 ">
            <div
              className={cn('flex items-center gap-1', {
                'justify-between': switchPlacement === 'end',
              })}
            >
              <FormLabel
                tooltip={t('html4excelTip')}
                className="text-sm text-text-secondary whitespace-break-spaces w-1/4"
              >
                {t('html4excel')}
              </FormLabel>
              <div className="flex-none">
                <FormControl>
                  <Switch
                    checked={field.value}
                    onCheckedChange={field.onChange}
                    data-testid="ds-settings-parser-excel-to-html-switch"
                  ></Switch>
                </FormControl>
              </div>
            </div>
            <div className="flex pt-1">
              <div className="w-1/4"></div>
              <FormMessage />
            </div>
          </FormItem>
        );
      }}
    />
  );
}
