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

import ThemeButton from '@/layouts/components/theme-button';
import { changeLanguageAsync, supportedLanguages } from '@/locales/config';
import { Languages } from 'lucide-react';
import { useTranslation } from 'react-i18next';

/**
 * 登录/注册页面的语言与主题切换组件。
 * 采用与 Header 一致的 SVG 图标样式，并集成 ThemeButton。
 */
export function LoginLanguageToggle() {
  const { i18n } = useTranslation();
  const currentLanguage = i18n.resolvedLanguage ?? i18n.language;

  // 切换下一个目标语言（支持 zh / en 切换）
  const handleToggleLanguage = () => {
    const nextLang = currentLanguage.startsWith('zh') ? 'en' : 'zh';
    changeLanguageAsync(nextLang);
  };

  const nextLangObj = supportedLanguages.find((item) => item.code !== currentLanguage);

  return (
    <div className="flex shrink-0 items-center justify-end gap-1">
      {/* 语言切换 SVG 按钮 */}
      <button
        type="button"
        onClick={handleToggleLanguage}
        aria-label={nextLangObj?.displayName ?? 'Switch Language'}
        title={nextLangObj?.displayName ?? 'Switch Language'}
        className="inline-flex size-8 shrink-0 items-center justify-center rounded p-0 text-text-secondary transition-colors hover:bg-muted hover:text-text-primary focus-visible:outline-none"
      >
        <Languages className="size-[1.05rem]" />
      </button>

      {/* 主题模式切换按钮 */}
      <ThemeButton />
    </div>
  );
}