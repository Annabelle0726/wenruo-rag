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

import { CardIdentityIcon } from '@/components/card-identity-icon';
import { Button } from '@/components/ui/button';
import { useChangeLanguage } from '@/hooks/logic-hooks';
import { useFetchUserInfo } from '@/hooks/use-user-setting-request';
import { cn } from '@/lib/utils';
import { Routes } from '@/routes';
import { BellRing, LucideLanguages } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation } from 'react-router';
import { BrandLockup } from './brand-lockup';
import { DesktopNavbar, MobileNavbar } from './global-navbar';
import { MobileMenuFooter } from './mobile-menu-footer';
import { NotificationCenter } from './notification-center';
import ThemeButton from './theme-button';
import { useHeaderNavLayout } from './use-header-nav-layout';

import { supportedLanguages } from '@/locales/config';

/**
 * One shared shape for every header control, so the right-hand cluster reads as a
 * single row of micro-components instead of a row of mixed buttons.
 */
const headerControlClass =
  'size-8 shrink-0 p-0 text-white/85 hover:bg-gov-header-hover hover:text-white focus-visible:bg-gov-header-hover focus-visible:text-white';

/**
 * Local override of the shared `--cable-nav-*` tokens.
 */
const headerNavTokens =
  '[--cable-nav-text:rgba(255,255,255,0.85)] [--cable-nav-text-hover:#ffffff] [--cable-nav-active-text:#ffffff] [--cable-nav-active-bg:#005c3f] [--cable-nav-indicator:#ffffff]';

export function Header({
  className,
  ...props
}: React.HTMLAttributes<HTMLElement>) {
  const { t, i18n } = useTranslation();
  const { pathname } = useLocation();
  const changeLanguage = useChangeLanguage();

  const {
    data: { language, avatar },
  } = useFetchUserInfo();

  // The notification bell owns the pending-invitation source itself, so the
  // header no longer reads the tenant list to decide whether to show a bell: the
  // bell is always present and its badge reports the unread count.

  // 获取当前正在使用的语言
  const currentLangCode = i18n.resolvedLanguage || language || 'zh';

  // 计算目标语言
  const nextLangCode = currentLangCode.startsWith('zh') ? 'en' : 'zh';
  const nextLangObj = supportedLanguages.find((x) => x.code === nextLangCode);

  const handleToggleLanguage = () => {
    changeLanguage(nextLangCode);
  };

  const {
    headerRef,
    logoRef,
    expandedRightMeasureRef,
    navMeasureRef,
    isCompact,
  } = useHeaderNavLayout(currentLangCode);

  return (
    <>
      <header
        ref={headerRef}
        key="app-navbar"
        className={cn(
          'page-gutter flex h-12 min-w-0 items-center gap-2 sm:gap-4',
          headerNavTokens,
          className,
        )}
        {...props}
      >
        <div className="inline-flex shrink-0 items-center gap-2">
          {isCompact && (
            <MobileNavbar
              renderFooter={(close) => <MobileMenuFooter onClose={close} />}
            />
          )}
          <div ref={logoRef} className="inline-flex shrink-0 items-center">
            <Link
              to={Routes.Root}
              aria-current={pathname === Routes.Root ? 'page' : undefined}
              className="brand-entry flex shrink-0 items-center gap-2 px-1 py-1 hover:bg-transparent"
              data-testid="brand-entry"
            >
              <BrandLockup />
              <span className="text-[15px] font-semibold tracking-tight text-white">
                {t('header.brandShort')}
              </span>
            </Link>
          </div>
        </div>

        {!isCompact && (
          <div className="flex min-w-0 flex-1 items-center overflow-x-clip">
            <DesktopNavbar />
          </div>
        )}

        {isCompact && <div className="flex-1" aria-hidden />}

        <div
          className={cn(
            'flex shrink-0 items-center justify-end',
            isCompact ? 'gap-0.5' : 'gap-1',
          )}
          data-testid="auth-status"
        >
          {/* 单击直接切换中/英文 */}
          <Button
            variant="ghost"
            className={headerControlClass}
            onClick={handleToggleLanguage}
            aria-label={nextLangObj?.displayName || 'Switch Language'}
            title={nextLangObj?.displayName || 'Switch Language'}
          >
            <LucideLanguages className="size-[1.05rem]" />
          </Button>

          {/* Always present: the drawer is the notification shell, and a bell that
              appeared only when a count was non-zero could never be discovered. */}
          <NotificationCenter className={headerControlClass} />

          {/* Dark/light switch. */}
          <ThemeButton className={headerControlClass} />

          <Link
            to={Routes.UserSetting}
            className={cn(
              'relative flex size-8 shrink-0 items-center justify-center',
              'ring-1 ring-white/40 transition-[box-shadow] hover:ring-white',
              !isCompact && 'ms-2',
            )}
            data-testid="settings-entrypoint"
          >
            <CardIdentityIcon
              kind="user"
              avatar={avatar}
              className="size-8"
              data-testid="account-identity"
            />
          </Link>
        </div>
      </header>

      {/* 隐藏的测量节点（用于响应式计算） */}
      <div
        className="pointer-events-none invisible fixed -left-[9999px] top-0"
        aria-hidden
      >
        <div ref={navMeasureRef}>
          <DesktopNavbar />
        </div>
        <div
          ref={expandedRightMeasureRef}
          className="inline-flex shrink-0 items-center justify-end gap-1"
        >
          <Button variant="ghost" className={headerControlClass}>
            <LucideLanguages className="size-[1.05rem]" />
          </Button>
          <Button variant="ghost" className={headerControlClass}>
            {/* The bell's own width comes from these classes, so measuring this
                mirror keeps the compact breakpoint exact without mounting a second
                dialog root off-screen. */}
            <BellRing className="size-[1.05rem]" />
          </Button>
          <ThemeButton className={headerControlClass} />
          <div className="relative ms-2 flex size-8 shrink-0 items-center justify-center">
            <CardIdentityIcon kind="user" avatar={avatar} className="size-8" />
          </div>
        </div>
      </div>
    </>
  );
}