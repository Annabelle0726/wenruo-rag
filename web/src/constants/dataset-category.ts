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

import { IDataset } from '@/interfaces/database/dataset';
import {
  Boxes,
  ClipboardCheck,
  Database,
  FileText,
  Layers,
  LucideIcon,
  ShieldCheck,
} from 'lucide-react';

/**
 * Industrial classification of a knowledge base, in the way cable-plant
 * documentation is actually filed. `General` is the fallback the resolver lands
 * on, and `Custom` exists only for knowledge bases whose owner filed them under
 * a tag of their own — it is never produced by keyword matching.
 */
export enum DatasetCategory {
  Bom = 'bom',
  Standard = 'standard',
  Spec = 'spec',
  Quality = 'quality',
  General = 'general',
  Custom = 'custom',
}

type DatasetCategoryDefinition = {
  /** Label for the first level of the navigation menu. */
  labelKey: string;
  /** Short label for the chip on a card. */
  chipKey: string;
  icon: LucideIcon;
  /** Sets --category-glow and --category-ink, so the tone lives in the theme. */
  toneClass: string;
  /** Needles matched against a knowledge base's name and description. */
  keywords: string[];
};

export const DatasetCategoryDefinitions: Record<
  DatasetCategory,
  DatasetCategoryDefinition
> = {
  [DatasetCategory.Bom]: {
    labelKey: 'datasetCategory.bom',
    chipKey: 'datasetCategory.chip.bom',
    icon: Layers,
    toneClass: 'category-tone-bom',
    keywords: ['bom', '配方', '截面', '结构', '物料', 'component', 'structure'],
  },
  [DatasetCategory.Standard]: {
    labelKey: 'datasetCategory.standard',
    chipKey: 'datasetCategory.chip.standard',
    icon: ShieldCheck,
    toneClass: 'category-tone-standard',
    keywords: [
      'gb',
      'gbt',
      'gb/t',
      '国标',
      'iec',
      '标准',
      '规范',
      'standard',
      'specification',
    ],
  },
  [DatasetCategory.Spec]: {
    labelKey: 'datasetCategory.spec',
    chipKey: 'datasetCategory.chip.spec',
    icon: FileText,
    toneClass: 'category-tone-spec',
    keywords: [
      '规格',
      '参数',
      '技术',
      '数据表',
      'spec',
      'tech',
      'datasheet',
      'parameter',
    ],
  },
  [DatasetCategory.Quality]: {
    labelKey: 'datasetCategory.quality',
    chipKey: 'datasetCategory.chip.quality',
    icon: ClipboardCheck,
    toneClass: 'category-tone-quality',
    keywords: [
      '质检',
      '检验',
      '审计',
      '合规',
      '质量',
      'quality',
      'audit',
      'compliance',
      'inspection',
    ],
  },
  [DatasetCategory.General]: {
    labelKey: 'datasetCategory.general',
    chipKey: 'datasetCategory.chip.general',
    icon: Database,
    toneClass: 'category-tone-general',
    keywords: [],
  },
  [DatasetCategory.Custom]: {
    labelKey: 'datasetCategory.custom',
    chipKey: 'datasetCategory.chip.custom',
    icon: Boxes,
    toneClass: 'category-tone-custom',
    keywords: [],
  },
};

/**
 * Order of the first navigation level. `Custom` is absent on purpose: an
 * owner's own tag is not a class of the plant's filing system, so those
 * knowledge bases are listed under the general bucket, while the card chip
 * still shows the tag the owner typed.
 */
export const DatasetCategoryNavOrder: DatasetCategory[] = [
  DatasetCategory.Bom,
  DatasetCategory.Standard,
  DatasetCategory.Spec,
  DatasetCategory.Quality,
  DatasetCategory.General,
];

export type DatasetCategoryResolution = {
  category: DatasetCategory;
  /** The owner's own tag, set only when the record declared one we cannot map. */
  customTag?: string;
};

const isAsciiKeyword = (keyword: string) => /^[a-z0-9/.]+$/.test(keyword);

const normaliseDeclared = (value: string) =>
  value.toLowerCase().replace(/[\s_/|\\-]+/g, '');

/**
 * Spellings a `category` field uses for the two classes that carry no keywords
 * of their own — without this a declared `通用/其他` would be read as an
 * owner's private tag and land in `Custom`. Matched on the normalised value, so
 * casing, spaces and separators do not matter.
 */
const DeclaredAliases: Record<string, DatasetCategory> = {
  general: DatasetCategory.General,
  default: DatasetCategory.General,
  generalother: DatasetCategory.General,
  other: DatasetCategory.General,
  通用: DatasetCategory.General,
  通用其他: DatasetCategory.General,
  其他: DatasetCategory.General,
  默认: DatasetCategory.General,
  custom: DatasetCategory.Custom,
  自定义: DatasetCategory.Custom,
};

/**
 * ASCII needles match on a word boundary so `GB` is not found inside `logbook`
 * and `BOM` is not found inside `bombardier`; CJK needles have no word
 * boundaries to match on, so they are plain substrings.
 */
const matchesKeyword = (haystack: string, keyword: string) => {
  if (!isAsciiKeyword(keyword)) {
    return haystack.includes(keyword);
  }

  const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  return new RegExp(`(^|[^a-z0-9])${escaped}([^a-z0-9]|$)`).test(haystack);
};

const matchAgainst = (haystack: string) =>
  DatasetCategoryNavOrder.find((category) =>
    DatasetCategoryDefinitions[category].keywords.some((keyword) =>
      matchesKeyword(haystack, keyword),
    ),
  );

/**
 * Classify one knowledge base.
 *
 * A `category` field wins over the name: its value is matched the same way the
 * name is, so both a clean enum value (`bom`) and the label an operator typed
 * (`GB/T 标准规范`) resolve. A value that matches nothing is the owner's own
 * filing, so it becomes `Custom` and the raw text is echoed back for the chip.
 * A knowledge base with neither field nor matching name falls back to
 * `General`.
 */
export const resolveDatasetCategory = (
  dataset: Pick<IDataset, 'name' | 'description'> & { category?: string | null },
): DatasetCategoryResolution => {
  const declared = dataset.category?.trim();

  if (declared) {
    const alias = DeclaredAliases[normaliseDeclared(declared)];

    if (alias) {
      return { category: alias };
    }

    const matched = matchAgainst(declared.toLowerCase());

    return matched
      ? { category: matched }
      : { category: DatasetCategory.Custom, customTag: declared };
  }

  const haystack = `${dataset.name ?? ''} ${dataset.description ?? ''}`.toLowerCase();

  return { category: matchAgainst(haystack) ?? DatasetCategory.General };
};

export type DatasetCategoryGroups = Record<DatasetCategory, IDataset[]>;

/**
 * Whether the class was chosen by a person rather than derived from the name.
 * The chip says which, so nobody wonders why a rename moved a knowledge base.
 */
export const isManualCategory = (
  dataset: Pick<IDataset, 'name' | 'description'> & { category?: string | null },
) => Boolean(dataset.category?.trim());

export const groupDatasetsByCategory = (
  datasets: IDataset[],
): DatasetCategoryGroups => {
  const groups: DatasetCategoryGroups = {
    [DatasetCategory.Bom]: [],
    [DatasetCategory.Standard]: [],
    [DatasetCategory.Spec]: [],
    [DatasetCategory.Quality]: [],
    [DatasetCategory.General]: [],
    [DatasetCategory.Custom]: [],
  };

  datasets.forEach((dataset) => {
    const { category } = resolveDatasetCategory(dataset);

    groups[category].push(dataset);
  });

  return groups;
};

/**
 * The knowledge bases a first-level navigation entry stands for. The general
 * entry also collects the owner's custom-tagged knowledge bases, so nothing is
 * unreachable from the menu.
 */
export const datasetsInNavCategory = (
  groups: DatasetCategoryGroups,
  category: DatasetCategory,
): IDataset[] =>
  category === DatasetCategory.General
    ? [...groups[DatasetCategory.General], ...groups[DatasetCategory.Custom]]
    : groups[category];
