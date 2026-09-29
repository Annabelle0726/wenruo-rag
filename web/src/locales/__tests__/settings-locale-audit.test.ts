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

import fs from 'fs';
import path from 'path';

import en from '../en';
import zh from '../zh';

/**
 * The Settings locale audit.
 *
 * It reads the U2/U2.1 SOURCE files and checks every translation key they use
 * against both bundles, because the failure this guards against is invisible in
 * review: a key that exists in no bundle is not rendered as the key, it is
 * rendered by `parseMissingKeyHandler` as a humanised sentence ("Capability chat"),
 * and a key that exists only in English silently serves English copy to a Chinese
 * reader. Both look like copy that simply was not translated.
 */

const WEB_ROOT = path.resolve(__dirname, '..', '..', '..');

/** Every file whose user-facing copy this audit owns. */
const AUDITED_FILES = [
  'src/pages/user-setting/index.tsx',
  'src/pages/user-setting/settings-nav.ts',
  'src/pages/user-setting/sidebar/index.tsx',
  'src/pages/user-setting/setting-model/index.tsx',
  'src/pages/user-setting/setting-model/provider-category.tsx',
  'src/pages/user-setting/setting-team/index.tsx',
  'src/pages/user-setting/setting-team/usage-policy.tsx',
  'src/pages/user-setting/usage-operations/index.tsx',
  'src/pages/user-setting/usage-operations/my-usage.tsx',
  'src/pages/user-setting/usage-operations/workspace-analytics.tsx',
  'src/pages/user-setting/usage-operations/provider-health.tsx',
  'src/pages/user-setting/usage-operations/retrieval-health.tsx',
  'src/pages/user-setting/usage-operations/components/coming-data-panel.tsx',
  'src/pages/user-setting/usage-operations/components/limit-standing-list.tsx',
  'src/pages/user-setting/usage-operations/components/read-model-notice.tsx',
  'src/pages/user-setting/usage-operations/components/usage-metric.tsx',
  'src/pages/user-setting/usage-operations/components/usage-range-filter.tsx',
  'src/pages/user-setting/usage-operations/components/usage-tables.tsx',
  'src/layouts/components/notification-center/index.tsx',
  'src/constants/model-provider-endpoint.ts',
];

/**
 * Keys the components build at runtime from a table, so a literal scan cannot see
 * them. They are asserted separately, and the list is deliberately explicit: a new
 * dynamic table must be added here rather than silently skipping the audit.
 */
const DYNAMIC_KEYS = [
  'setting.capabilityChat',
  'setting.capabilityEmbedding',
  'setting.capabilityRerank',
  'setting.capabilityVlm',
  'setting.capabilityAsr',
  'setting.capabilityTts',
  'setting.capabilityOcr',
  'setting.modelManagedApi',
  'setting.modelPrivateEndpoint',
  'setting.modelUnclassified',
  'usage.providerGroupManaged',
  'usage.providerGroupPrivate',
  'usage.providerGroupUnclassified',
  'usage.providerGroupManagedHint',
  'usage.providerGroupPrivateHint',
  'usage.providerGroupUnclassifiedHint',
  'usage.limitCallsPerMinute',
  'usage.limitCallsPerDay',
  'usage.limitCallsPerMonth',
  'usage.limitTokensPerDay',
  'usage.limitTokensPerMonth',
  'usage.limitCostPerDay',
  'usage.limitCostPerMonth',
  'usage.myUsage',
  'usage.workspaceAnalytics',
  'usage.providerHealth',
  'usage.retrievalHealth',
  'setting.roleOwner',
  'setting.roleAdmin',
  'setting.roleMember',
  'setting.roleInvite',
];

/** Values that are legitimately identical in both languages. */
const SAME_IN_BOTH = new Set([
  'setting.capabilityVlm',
  'setting.capabilityOcr',
  'setting.modelManagedApi',
  'setting.modelPrivateEndpoint',
  'setting.modelUnclassified',
  'usage.providerGroupManaged',
  'usage.providerGroupPrivate',
  'usage.providerGroupUnclassified',
]);

const bundleOf = (module: any) => module?.translation ?? module;
const bundles = { en: bundleOf(en), zh: bundleOf(zh) };

const resolveKey = (bundle: Record<string, any>, key: string): unknown =>
  key.split('.').reduce<any>((node, segment) => {
    if (node && typeof node === 'object' && segment in node) {
      return node[segment];
    }
    return undefined;
  }, bundle);

const readSourceKeys = (): string[] => {
  const keys = new Set<string>();

  AUDITED_FILES.forEach((relative) => {
    const source = fs.readFileSync(path.join(WEB_ROOT, relative), 'utf8');
    // `t('a.b')` and the labelKey fields of the navigation model.
    for (const match of source.matchAll(/\bt\(\s*'([A-Za-z0-9_.]+)'/g)) {
      keys.add(match[1]);
    }
    for (const match of source.matchAll(/labelKey:\s*'([A-Za-z0-9_.]+)'/g)) {
      keys.add(match[1]);
    }
    for (const match of source.matchAll(/titleKey:\s*'([A-Za-z0-9_.]+)'/g)) {
      keys.add(match[1]);
    }
    for (const match of source.matchAll(/descriptionKey:\s*'([A-Za-z0-9_.]+)'/g)) {
      keys.add(match[1]);
    }
    for (const match of source.matchAll(/pendingKeys\s*=\s*\{([^}]*)\}/g)) {
      for (const key of match[1].matchAll(/'([A-Za-z0-9_.]+)'/g)) {
        keys.add(key[1]);
      }
    }
  });

  return Array.from(keys).sort();
};

const referencedKeys = Array.from(
  new Set([...readSourceKeys(), ...DYNAMIC_KEYS]),
).sort();

describe('every referenced Settings key resolves in BOTH locales', () => {
  it('found a meaningful number of keys to audit', () => {
    // Guards against the scanner silently matching nothing and passing.
    expect(referencedKeys.length).toBeGreaterThan(80);
  });

  it('has no key that resolves to nothing', () => {
    const missing = referencedKeys.filter(
      (key) =>
        typeof resolveKey(bundles.en, key) !== 'string' ||
        typeof resolveKey(bundles.zh, key) !== 'string',
    );

    expect(missing).toEqual([]);
  });

  it('has no key whose value is empty', () => {
    const empty = referencedKeys.filter((key) => {
      const value = resolveKey(bundles.zh, key) as string;
      return value.trim().length === 0;
    });

    expect(empty).toEqual([]);
  });

  it('never lets a key fall through to the humanised missing-key handler', () => {
    // The handler turns `setting.capabilityChat` into "Capability chat" in en and
    // (because the bundle is absent) into the same English sentence in zh. If a
    // value equals that humanised leaf, the bundle did not really answer.
    const humanise = (key: string) =>
      (key.split('.').pop() ?? key)
        .replace(/[_-]+/g, ' ')
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .trim()
        .toLowerCase()
        .replace(/^./, (first) => first.toUpperCase());

    const suspicious = referencedKeys.filter(
      (key) => resolveKey(bundles.zh, key) === humanise(key),
    );

    expect(suspicious).toEqual([]);
  });
});

describe('no Settings surface is left untranslated', () => {
  it('does not serve the English string from the Chinese bundle', () => {
    const untranslated = referencedKeys.filter((key) => {
      if (SAME_IN_BOTH.has(key)) {
        return false;
      }
      const english = resolveKey(bundles.en, key);
      const chinese = resolveKey(bundles.zh, key);
      return english === chinese;
    });

    expect(untranslated).toEqual([]);
  });

  it('keeps the Chinese bundle free of plain English sentences', () => {
    // A Chinese value that is pure ASCII words is a value nobody translated.
    const englishOnly = referencedKeys.filter((key) => {
      if (SAME_IN_BOTH.has(key)) {
        return false;
      }
      const value = resolveKey(bundles.zh, key) as string;
      const withoutPlaceholders = value.replace(/\{\{[^}]*\}\}/g, '');
      return !/[\u4e00-\u9fff]/.test(withoutPlaceholders);
    });

    expect(englishOnly).toEqual([]);
  });
});

describe('the required Chinese product terminology', () => {
  const expected: Record<string, string> = {
    'setting.usageOperations': '用量与运维',
    'usage.myUsage': '我的用量',
    'usage.workspaceAnalytics': '工作区分析',
    'usage.providerHealth': '服务商健康',
    'usage.retrievalHealth': '检索健康',
    'setting.usagePolicy': '用量策略',
    'setting.teamMembersAndRoles': '成员与角色',
    'setting.teamDepartments': '部门管理',
    'setting.model': '模型提供商',
    'setting.modelManagedApi': '托管 API',
    'setting.modelPrivateEndpoint': '私有端点',
    'setting.modelUnclassified': '未分类',
    'setting.capabilities': '能力',
    'setting.capabilityChat': '对话',
    'setting.capabilityEmbedding': '向量化',
    'setting.capabilityRerank': '重排序',
  };

  it.each(Object.entries(expected))('%s is %s', (key, value) => {
    expect(resolveKey(bundles.zh, key)).toBe(value);
  });
});

describe('no U2.1 surface hard-codes user-facing English', () => {
  /** ASCII words that are legitimately untranslated (proper nouns, units, file names). */
  const ALLOWED = new Set([
    'API',
    'VLM',
    'OCR',
    'ASR',
    'TTS',
    'Redis',
    'ID',
    'URL',
    'AI',
    'vLLM',
    'TEI',
    'Ollama',
    'OpenAI',
    'Gemini',
    'DeepSeek',
    'SiliconFlow',
  ]);

  it('renders copy through t() rather than a literal text node', () => {
    const offenders: string[] = [];

    AUDITED_FILES.forEach((relative) => {
      const source = fs.readFileSync(path.join(WEB_ROOT, relative), 'utf8');
      source.split('\n').forEach((line, index) => {
        const trimmed = line.trim();
        if (trimmed.startsWith('*') || trimmed.startsWith('//')) {
          return;
        }
        // A JSX text node with at least two words, outside an expression.
        const textNode = line.match(/>\s*([A-Za-z][A-Za-z0-9 ,.'&/:-]{6,}?)\s*</);
        if (!textNode) {
          return;
        }
        const words = textNode[1]
          .split(/[\s,]+/)
          .filter((word) => /[A-Za-z]{3,}/.test(word));
        if (words.length < 2) {
          return;
        }
        if (words.every((word) => ALLOWED.has(word.replace(/[^A-Za-z]/g, '')))) {
          return;
        }
        offenders.push(`${relative}:${index + 1}: ${textNode[1]}`);
      });
    });

    expect(offenders).toEqual([]);
  });

  it('passes no English literal to aria-label, title or placeholder', () => {
    const offenders: string[] = [];

    AUDITED_FILES.forEach((relative) => {
      const source = fs.readFileSync(path.join(WEB_ROOT, relative), 'utf8');
      source.split('\n').forEach((line, index) => {
        if (line.trim().startsWith('*') || line.trim().startsWith('//')) {
          return;
        }
        const match = line.match(
          /\b(aria-label|title|placeholder)=(["'])([A-Za-z][^"']{3,})\2/,
        );
        if (match) {
          offenders.push(`${relative}:${index + 1}: ${match[1]}=${match[3]}`);
        }
      });
    });

    expect(offenders).toEqual([]);
  });
});
