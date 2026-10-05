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

import brandMark from '@/assets/icon/brand-mark.png';
import brandPoster from '@/assets/icon/brand-poster.jpg';
import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';

export type BrandLogoVariant = 'mark' | 'lockup' | 'poster';

type BrandLogoProps = {
  variant?: BrandLogoVariant;
  className?: string;
  alt?: string;
};

export function BrandLogo({
  variant = 'mark',
  className,
  alt,
}: BrandLogoProps) {
  const { t } = useTranslation();

  if (variant === 'lockup') {
    return (
      <div className={cn('inline-flex items-center gap-3 bg-transparent', className)}>
        <img
          src={brandMark}
          alt={alt ?? t('header.brandShort')}
          className="h-9 w-auto shrink-0 object-contain"
        />
        <div className="flex flex-col justify-center leading-none">
          <span className="text-lg font-bold tracking-tight text-text-primary">
            芯导软件
          </span>
          <span className="mt-1 text-[10px] font-semibold tracking-wider text-text-tertiary">
            XINDAO SOFTWARE
          </span>
        </div>
      </div>
    );
  }

  if (variant === 'poster') {
    return (
      <img
        src={brandPoster}
        alt={alt ?? t('header.brandShort')}
        className={cn('object-contain', className)}
      />
    );
  }

  return (
    <img
      src={brandMark}
      alt={alt ?? t('header.brandShort')}
      className={cn('object-contain', className)}
    />
  );
}