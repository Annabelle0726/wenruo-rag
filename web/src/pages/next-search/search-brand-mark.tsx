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

import { BrandLogo } from '@/components/brand-logo';
import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';

/**
 * The search surfaces' brand mark: the same logo the app bar and the assistant
 * avatar use, so the search hero cannot drift into showing the upstream wordmark
 * (or a hard-coded teal-to-indigo gradient) again. The embed button that used to
 * sit beside it is gone — this deployment does not publish search apps for
 * embedding, so it was a paper plane pointing at a feature nobody uses.
 */
export function SearchBrandMark({
  onClick,
}: {
  onClick?: React.MouseEventHandler<HTMLHeadingElement>;
}) {
  const { t } = useTranslation();

  return (
    <div className="flex items-center justify-center">
      <h1
        onClick={onClick}
        className={cn(
          'flex items-center gap-4 text-4xl font-bold tracking-tight text-cable-gradient select-none sm:text-5xl',
          onClick && 'cursor-pointer transition-opacity hover:opacity-90',
        )}
      >
        <span className="flex shrink-0 items-center justify-center">
          <BrandLogo className="h-9 w-auto object-contain sm:h-10" />
        </span>
        <span>{t('header.brandShort')}</span>
      </h1>
    </div>
  );
}