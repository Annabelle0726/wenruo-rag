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
 * single row of micro-components instead of a row of mixed buttons. The 32px box,
 * the ink and the hover/focus states all live in `.shell-header-control`; the
 * utilities here only win the merge against `Button`'s own size/padding.
 */
const headerControlClass = 'shell-header-control size-8 shrink-0 p-0';

/**
 * Local override of the shared `--cable-nav-*` tokens.
 *
 * The bar is a solid green block in both themes, so the whole nav palette is
 * replaced rather than tuned: idle is white at 86%, hover adds a 10% white wash,
 * and the selected item adds a 16% wash plus the 2px brand-mint indicator. Mint
 * (`#b6eeda` on `#007a53`) is the one place the shell uses a brand hue on the
 * chrome itself, and it is what makes "where am I" readable at a glance without
 * adding a second colour to the bar.
 */
const headerNavTokens =
  '[--cable-nav-text:var(--shell-header-ink)] [--cable-nav-text-hover:var(--shell-header-ink-strong)] [--cable-nav-hover-bg:var(--shell-header-wash)] [--cable-nav-active-text:var(--shell-header-ink-strong)] [--cable-nav-active-bg:var(--shell-header-active-bg)] [--cable-nav-indicator:var(--shell-header-indicator)]';

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
      {/*
        顶栏三等分：品牌区 / 主导航 / 工具区。三区之间各有一条 24px 高的 1px
        白线（`.shell-header-rail`），左区与右区因此各有一个明确的边界，导航
        不会读作"从 logo 一路排到铃铛"的一串链接。56px 高度给 32px 控件上下
        各留 12px，图标与文字共用一条中线。
      */}
      <header
        ref={headerRef}
        key="app-navbar"
        className={cn(
          'page-gutter flex h-14 min-w-0 items-center gap-3',
          headerNavTokens,
          className,
        )}
        {...props}
      >
        <div className="inline-flex shrink-0 items-center gap-2.5">
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
              <span className="shell-header-brand whitespace-nowrap">
                {t('header.brandShort')}
              </span>
            </Link>
          </div>
        </div>

        {!isCompact && <span aria-hidden className="shell-header-rail" />}

        {!isCompact ? (
          <div className="flex min-w-0 flex-1 items-center overflow-x-clip">
            <DesktopNavbar />
          </div>
        ) : (
          <div className="flex-1" aria-hidden />
        )}

        {/* 工具区：语言/通知/主题共用一个 1px 描边容器（一块仪表板），
            账号入口是它右侧独立的一格。 */}
        <div
          className="shell-header-instruments shrink-0"
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
        </div>

        <Link
          to={Routes.UserSetting}
          className="shell-header-account"
          aria-current={pathname.startsWith(Routes.UserSetting) ? 'page' : undefined}
          data-testid="settings-entrypoint"
        >
          <CardIdentityIcon
            kind="user"
            avatar={avatar}
            className="size-8"
            data-testid="account-identity"
          />
        </Link>
      </header>

      {/* 隐藏的测量节点（用于响应式计算）。镜像必须和真实结构同宽：
          仪器容器与账号方格的 class 同时出现在两边，否则紧凑断点会算错。 */}
      <div
        className="pointer-events-none invisible fixed -left-[9999px] top-0"
        aria-hidden
      >
        <div ref={navMeasureRef}>
          <DesktopNavbar />
        </div>
        <div
          ref={expandedRightMeasureRef}
          className="inline-flex shrink-0 items-center gap-3"
        >
          <div className="shell-header-instruments shrink-0">
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
          </div>
          <div className="shell-header-account">
            <CardIdentityIcon kind="user" avatar={avatar} className="size-8" />
          </div>
        </div>
      </div>
    </>
  );
}