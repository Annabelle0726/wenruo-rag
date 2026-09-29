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

import { cn } from '@/lib/utils';
import { LucideCircleDashed, LucideInfo } from 'lucide-react';
import { useTranslation } from 'react-i18next';

/**
 * An honest "there is nothing to show yet" panel.
 *
 * It exists so a page can be built BEFORE its data source is: it states that no
 * observation is recorded, names the fact that is missing, and never fills the
 * space with an example number, a mock percentage or a sample alert. Every
 * coming-data surface in this console uses it, so "empty" can never be mistaken
 * for "green".
 */
export function ComingDataPanel({
  titleKey,
  descriptionKey,
  pendingKeys = [],
  testId,
  className,
  tone = 'neutral',
}: {
  titleKey: string;
  descriptionKey: string;
  /** What is still missing, one translation key per line. */
  pendingKeys?: string[];
  testId?: string;
  className?: string;
  tone?: 'neutral' | 'unavailable';
}) {
  const { t } = useTranslation();
  const Icon = tone === 'unavailable' ? LucideCircleDashed : LucideInfo;

  return (
    <div
      className={cn(
        'ceramic-relief flex flex-col gap-3 rounded-[2px] p-4',
        className,
      )}
      data-testid={testId}
    >
      <div className="flex items-start gap-2">
        <Icon
          className={cn(
            'mt-0.5 size-4 shrink-0',
            tone === 'unavailable'
              ? 'text-text-disabled'
              : 'text-accent-primary',
          )}
        />
        <div className="flex min-w-0 flex-col gap-1">
          <p className="text-sm text-text-primary">{t(titleKey)}</p>
          <p className="text-xs text-text-secondary">{t(descriptionKey)}</p>
        </div>
      </div>

      {pendingKeys.length > 0 && (
        <ul className="flex flex-col gap-1 ps-6 text-xs text-text-secondary">
          {pendingKeys.map((key) => (
            <li key={key} className="list-disc">
              {t(key)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
