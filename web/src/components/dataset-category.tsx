/*
 *  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
 *  Modifications Copyright 2026 线缆工业智搜平台. All Rights Reserved.
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

import {
  DatasetCategory,
  DatasetCategoryDefinitions,
  isManualCategory,
  resolveDatasetCategory,
} from '@/constants/dataset-category';
import { IDataset } from '@/interfaces/database/dataset';
import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';
import { RAGFlowAvatar } from './ragflow-avatar';

type DatasetCategoryIconProps = {
  category: DatasetCategory;
  className?: string;
  /** Glyph size inside the frame; the frame itself is sized with `className`. */
  iconClassName?: string;
  style?: React.CSSProperties;
};

/**
 * The class icon in its frame, sized to the 32px slot the card avatar used to
 * occupy so a card's outer box does not change. Sized by the caller when a
 * sidebar header needs a taller mark.
 *
 * The tile is a neutral surface with the shared 1px hairline rather than a green
 * one: the glyph carries the class colour (`--category-ink`), and a green field
 * behind an orange BOM mark or a violet custom mark would fight it.
 */
export function DatasetCategoryIcon({
  category,
  className,
  iconClassName,
  style,
}: DatasetCategoryIconProps) {
  const { icon: Icon, toneClass } = DatasetCategoryDefinitions[category];

  return (
    <span
      style={style}
      className={cn(
        'category-halo flex size-8 shrink-0 items-center justify-center rounded-lg border border-panel-border bg-bg-title',
        toneClass,
        className,
      )}
    >
      <Icon className={cn('category-ink size-4', iconClassName)} aria-hidden />
    </span>
  );
}

/**
 * How a knowledge base shows its mark, everywhere it is shown: the owner's
 * uploaded image when there is one, the class icon otherwise.
 *
 * The list card, the detail sidebar's header and the compilation header all render
 * this, so the mark a card shows is the mark the page it opens shows — the header
 * used to fall back to `RAGFlowAvatar` and print the first character of the name
 * instead.
 */
export function DatasetIdentityMark({
  dataset,
  className,
  iconClassName,
  style,
}: {
  dataset: Pick<IDataset, 'name' | 'description' | 'avatar' | 'category'>;
  className?: string;
  iconClassName?: string;
  /** Grid placement, for the sidebar header that positions the mark by area. */
  style?: React.CSSProperties;
}) {
  if (dataset.avatar) {
    return (
      <RAGFlowAvatar
        avatar={dataset.avatar}
        name={dataset.name}
        className={className}
        style={style}
      />
    );
  }

  const { category } = resolveDatasetCategory(dataset);

  return (
    <DatasetCategoryIcon
      category={category}
      className={className}
      iconClassName={iconClassName}
      style={style}
    />
  );
}

type DatasetCategoryChipProps = {
  dataset: Pick<IDataset, 'name' | 'description'> & {
    category?: string | null;
  };
  className?: string;
};

/**
 * The class chip shown in the corner of a knowledge-base card. An owner's own
 * tag wins over the class label: the chip shows the text they typed while the
 * icon stays the custom-tag mark. The tooltip says whether the class was chosen
 * by hand or derived from the name, because a rename can move a knowledge base
 * that nobody ever classified.
 */
export function DatasetCategoryChip({
  dataset,
  className,
}: DatasetCategoryChipProps) {
  const { t } = useTranslation();
  const { category, customTag } = resolveDatasetCategory(dataset);
  const {
    chipKey,
    icon: Icon,
    toneClass,
  } = DatasetCategoryDefinitions[category];

  return (
    <span
      title={
        isManualCategory(dataset)
          ? t('datasetCategory.manualHint')
          : t('datasetCategory.autoHint')
      }
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded-full border border-cable-hairline px-2 py-0.5 text-xs',
        toneClass,
        className,
      )}
    >
      <Icon className="category-ink size-3" aria-hidden />
      <span className="max-w-[7rem] truncate text-text-secondary">
        {customTag ?? t(chipKey)}
      </span>
    </span>
  );
}
