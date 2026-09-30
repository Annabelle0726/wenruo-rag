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
  [SETTINGS_PATHS.model]: <LucideBox className="size-[1em]" />,
  [SETTINGS_PATHS.team]: <LucideUsers className="size-[1em]" />,
  [SETTINGS_PATHS.usage]: <LucideActivity className="size-[1em]" />,
  [SETTINGS_PATHS.profile]: <LucideUser className="size-[1em]" />,
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
                <div className="flex items-center gap-0.5">
                  {/* The chevron toggles the branch; the label navigates to the
                      section itself. One control cannot do both, and a reader who
                      wants only to open the tree must not be moved off the page
                      they are on. */}
                  {hasChildren ? (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={t('setting.toggleSection', {
                        section: sectionLabel(t, section.labelKey),
                      })}
                      aria-expanded={expanded}
                      className="hidden size-6 shrink-0 p-0 text-content-tertiary hover:text-content-primary md:flex"
                      onClick={() => toggleSection(section.path)}
                      data-testid={`${section.testId}-toggle`}
                    >
                      <ChevronRight
                        className={cn(
                          'size-3.5 transition-transform',
                          expanded && 'rotate-90',
                        )}
                      />
                    </Button>
                  ) : (
                    <span
                      className="hidden size-6 shrink-0 md:block"
                      aria-hidden
                    />
                  )}

                  {/* One row height, one ink, one selected idiom for both levels:
                      the section label is 14px (not 16px, which made the rail
                      louder than the page it opens) and its selected state is the
                      same 2px brand marker the child uses. */}
                  <Button
                    block
                    variant="ghost"
                    aria-label={sectionLabel(t, section.labelKey)}
                    aria-current={isActiveSection ? 'page' : undefined}
                    className={cn(
                      'settings-rail-item justify-start px-2.5 max-md:size-9 max-md:justify-center max-md:p-0 md:px-3',
                      'min-w-0 flex-1',
                      isActiveSection && 'settings-rail-item-active',
                    )}
                    onClick={() => goTo(section.path)}
                    data-testid={section.testId}
                  >
                    <span className="flex items-center gap-2.5 max-md:gap-0">
                      {SECTION_ICONS[section.path]}
                      <span className="hidden truncate md:inline">
                        {sectionLabel(t, section.labelKey)}
                      </span>
                    </span>
                  </Button>
                </div>

                {/* Second level: indented rows behind a hairline, so the branch
                    reads as belonging to the section above it. */}
                {hasChildren && expanded && (
                  <ul
                    className="ms-3.5 mt-0.5 hidden flex-col gap-0.5 border-s border-cable-hairline ps-2 md:flex"
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
