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

import {BrandLogo} from '@/components/brand-logo';
import {
  LucideBrain,
  LucideBoxes,
  LucideClipboardCheck,
  LucideFileText,
} from 'lucide-react';
import {useTranslation} from 'react-i18next';

/**
 * Feature list of the brand column. The icon carries the brand green, the row
 * holds the copy, and both come from tokens so the two themes stay a token swap
 * rather than a stack of `dark:` variants.
 */
const Features = [
  {
    icon: LucideFileText,
    title: 'hero.featureHybridSearch',
  },
  {
    icon: LucideBrain,
    title: 'hero.featureAgentMemory',
  },
  {
    icon: LucideClipboardCheck,
    title: 'hero.featureProcurementReview',
  },
  {
    icon: LucideBoxes,
    title: 'hero.featureBomQuality',
  },
];

/**
 * A restrained product introduction beside the sign-in form.
 * Background cable artwork is rendered once at page level so the form and hero
 * share a single, low-contrast technical texture.
 */
export function LoginHero() {
  const { t } = useTranslation('translation', { keyPrefix: 'login' });
  const { t: tHeader } = useTranslation('translation', { keyPrefix: 'header' });

  return (
    <section className="relative isolate hidden min-w-0 flex-col gap-6 lg:col-span-5 lg:flex lg:pr-12">
      <div className="relative z-10 flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <span className="flex h-12 w-fit items-center justify-center bg-transparent">
            <BrandLogo variant="lockup" className="login-hero-brand h-10 w-fit" />
          </span>

          <h1 className="flex items-start gap-2 text-3xl leading-snug font-semibold text-text-primary">
            <span aria-hidden className="mt-1.5 h-5 w-1 shrink-0 bg-cable-brand" />
            {tHeader('heroTitle')}
          </h1>

          <p className="max-w-[38rem] text-sm leading-relaxed text-content-secondary">
            {tHeader('heroSubtitle')}
          </p>
        </div>

        <ul className="grid max-w-[34rem] grid-flow-col grid-cols-2 grid-rows-2 gap-2.5">
          {Features.map(({ icon: Icon, title }) => (
            <li
              key={title}
              className="flex min-h-11 items-center gap-2.5 border border-table-border px-3 py-2"
            >
              <Icon className="size-4 shrink-0 text-cable-brand" />
              <p className="text-sm font-medium text-text-primary">{t(title)}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}