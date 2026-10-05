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

import { CardIdentityIcon } from '@/components/card-identity-icon';
import ThemeSwitch from '@/components/theme-switch';
import { Button } from '@/components/ui/button';
import { Domain } from '@/constants/common';
import { useLogout } from '@/hooks/use-login-request';
import {
  useFetchSystemVersion,
  useFetchUserInfo,
} from '@/hooks/use-user-setting-request';
import { cn } from '@/lib/utils';
import { TFunction } from 'i18next';
import {
  ChevronDown,
  ChevronRight,
  LucideActivity,
  LucideBox,
  LucideLogOut,
  LucideUser,
  LucideUsers,
} from 'lucide-react';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';

import RoleTag from '@/components/role-tag';
import { SETTINGS_PATHS } from '../settings-nav';
import { useSettingsNav } from './hooks';

/**
 * One icon per section, kept out of the navigation model so the model stays plain
 * data that a test can assert without a renderer.
 */
const SECTION_ICONS: Record<string, React.ReactNode> = {
  // 16px glyphs in the row's 20px box, the recipe the Dataset rail's rows use.
  [SETTINGS_PATHS.model]: <LucideBox className="size-4" />,
  [SETTINGS_PATHS.team]: <LucideUsers className="size-4" />,
  [SETTINGS_PATHS.usage]: <LucideActivity className="size-4" />,
  [SETTINGS_PATHS.profile]: <LucideUser className="size-4" />,
};

const sectionLabel = (t: TFunction, labelKey: string) => t(labelKey);

export function SideBar() {
  const { data: userInfo } = useFetchUserInfo();
  const { version, fetchSystemVersion } = useFetchSystemVersion();
  const { t } = useTranslation();
  useEffect(() => {
    if (location.host !== Domain) {
      fetchSystemVersion();
    }
  }, [fetchSystemVersion]);
  const { logout } = useLogout();
  const {
    sections,
    activeSection,
    activeChild,
    isExpanded,
    toggleSection,
    goTo,
  } = useSettingsNav();

  return (
    // `h-full min-h-0` matches the settings panel next to it: the rail is the
    // same height as the content area, and the menu list is the only part that
    // scrolls. The right edge is the rail's own ceramic seam, so the panel beside
    // it needs no border of its own.
    <aside className="ceramic-rail ceramic-seam-r flex h-full min-h-0 w-16 flex-col overflow-hidden md:w-[303px]">
      <header className="px-2 pt-5 md:px-4 md:pt-5">
        {/* The account block sits in its own relief capsule, so the rail reads as
            a canvas with a card on it rather than as one flat slab. */}
        <h1 className="ceramic-relief flex items-center justify-center gap-2.5 rounded-full px-2 py-2 font-normal md:justify-start md:px-3">
          <CardIdentityIcon
            kind="user"
            avatar={userInfo?.avatar}
            data-testid="account-identity"
          />

          <div className="hidden min-w-0 flex-col items-start gap-1 md:flex">
            <p className="text-sm text-text-primary truncate">
              {userInfo?.email}
            </p>
            <div className="flex items-center gap-2">
              <RoleTag role={userInfo?.role} />
            </div>
          </div>
        </h1>
      </header>

      <nav className="min-h-0 flex-1 overflow-auto py-1 mt-3">
        <ul className="flex flex-col gap-0.5 px-2 md:px-3 md:gap-1">
          {sections.map((section) => {
            const isActiveSection = activeSection?.path === section.path;
            const expanded = isExpanded(section.path);
            const hasChildren = section.children.length > 0;

            return (
              <li key={section.path} className="w-full">
                {/* ONE clickable row, as the Dataset configuration row is: the icon
                    sits in a fixed 20px box, the title follows it at the same 12px
                    gap, and the branch chevron closes the row - all inside this single
                    hit target, so the chevron is never a second control floating at
                    the rail's edge. The click does what the two controls used to do
                    together: it navigates to the section and, when the section has
                    children, toggles its branch. The surface, its hover and its active
                    step are the Dataset row's (`bg-accent-primary-5` /
                    `active:bg-accent-primary-10`), so the rail is one vocabulary. */}
                <Button
                  block
                  variant="ghost"
                  aria-label={sectionLabel(t, section.labelKey)}
                  aria-current={isActiveSection ? 'page' : undefined}
                  aria-expanded={hasChildren ? expanded : undefined}
                  aria-controls={
                    hasChildren ? `${section.testId}-children` : undefined
                  }
                  className={cn(
                    'min-w-0 w-full justify-start gap-3 py-2 relative h-9 text-sm font-semibold transition-colors',
                    'hover:bg-accent-primary-5 hover:text-accent-primary',
                    'focus-visible:bg-accent-primary-5 focus-visible:text-accent-primary',
                    'active:bg-accent-primary-10 active:text-accent-primary',
                    'px-2 max-md:size-9 max-md:justify-center max-md:p-0',
                    (isActiveSection || expanded) &&
                      'bg-accent-primary-5 text-accent-primary',
                  )}
                  onClick={() => {
                    goTo(section.path);
                    if (hasChildren) {
                      toggleSection(section.path);
                    }
                  }}
                  data-testid={section.testId}
                >
                  <span className="flex size-5 shrink-0 items-center justify-center">
                    {SECTION_ICONS[section.path]}
                  </span>
                  <span className="hidden min-w-0 truncate text-left md:inline">
                    {sectionLabel(t, section.labelKey)}
                  </span>
                  {/* The same two icons the Dataset branch indicator uses, with no
                      rotation and no transform: open reads as a down chevron, folded
                      as a left one, and only colours transition. The compact icon rail
                      has no room for it. */}
                  {hasChildren &&
                    (expanded ? (
                      <ChevronDown className="ms-1 hidden size-3.5 shrink-0 md:block" />
                    ) : (
                      <ChevronRight className="ms-1 hidden size-3.5 shrink-0 md:block" />
                    ))}
                </Button>

                {/* Second level: indented rows behind a hairline, so the branch
                    reads as belonging to the section above it. The indent matches
                    the Dataset configuration submenu's (`ms-5 ps-2.5`), which puts a
                    child's label just inside its parent's label. */}
                {hasChildren && expanded && (
                  <ul
                    className="ms-5 mt-0.5 hidden flex-col gap-0.5 border-s border-cable-hairline ps-2.5 md:flex"
                    data-testid={`${section.testId}-children`}
                  >
                    {section.children.map((child) => {
                      const isActiveChild = activeChild?.path === child.path;
                      return (
                        <li key={child.path}>
                          <Button
                            block
                            variant="ghost"
                            aria-current={isActiveChild ? 'page' : undefined}
                            className={cn(
                              'settings-rail-child w-full',
                              isActiveChild && 'settings-rail-child-active',
                            )}
                            onClick={() => goTo(child.path)}
                            data-testid={child.testId}
                          >
                            <span className="truncate">
                              {t(child.labelKey)}
                            </span>
                          </Button>
                        </li>
                      );
                    })}
                  </ul>
                )}

                {/* Compact screens keep the icon rail only: the child list cannot
                    fit beside the account capsule, so the second level is reached
                    by opening the section itself. */}
              </li>
            );
          })}
        </ul>
      </nav>

      <footer className="mt-auto p-2 md:p-4">
        <div className="mb-4 hidden items-center justify-between gap-2 md:flex">
          <span className="settings-field-hint font-mono">{version}</span>

          <ThemeSwitch />
        </div>

        <Button
          block
          size="lg"
          variant="transparent"
          aria-label={t('setting.logout')}
          className="ceramic-relief h-9 text-content-secondary hover:text-state-error max-md:mx-auto max-md:size-9 max-md:justify-center max-md:p-0"
          onClick={() => logout()}
        >
          <LucideLogOut className="size-[1em] md:hidden" />
          <span className="hidden md:inline">{t('setting.logout')}</span>
        </Button>
      </footer>
    </aside>
  );
}
