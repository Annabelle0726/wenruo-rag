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
import { Routes } from '@/routes';
import { TFunction } from 'i18next';
import {
  LucideActivity,
  LucideBox,
  LucideLogOut,
  LucideUser,
  LucideUsers,
} from 'lucide-react';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';

import RoleTag from '@/components/role-tag';
import { useHandleMenuClick } from './hooks';

/**
 * The settings rail, in the order the console presents it.
 *
 * The three operating sections come first - Model Providers, Team, and Usage &
 * Operations - and the account section (Profile) stays last. The rail is the
 * navigation; which of a section's views a caller may OPEN is decided inside the
 * section itself, because a rail entry that hid a page would still leave the
 * route reachable.
 */
const menuItems = (t: TFunction) => [
  {
    icon: <LucideBox className="size-[1em]" />,
    label: t('setting.model'),
    key: Routes.Model,
    'data-testid': 'settings-nav-model-providers',
  },
  {
    icon: <LucideUsers className="size-[1em]" />,
    label: t('setting.team'),
    key: Routes.Team,
    'data-testid': 'settings-nav-team',
  },
  {
    icon: <LucideActivity className="size-[1em]" />,
    label: t('setting.usageOperations'),
    key: Routes.Usage,
    'data-testid': 'settings-nav-usage-operations',
  },
  {
    icon: <LucideUser className="size-[1em]" />,
    label: t('setting.profile'),
    key: Routes.Profile,
    'data-testid': 'settings-nav-profile',
  },
];

export function SideBar() {
  const { data: userInfo } = useFetchUserInfo();
  const { handleMenuClick, active: activeItemKey } = useHandleMenuClick();
  const { version, fetchSystemVersion } = useFetchSystemVersion();
  const { t } = useTranslation();
  useEffect(() => {
    if (location.host !== Domain) {
      fetchSystemVersion();
    }
  }, [fetchSystemVersion]);
  const { logout } = useLogout();

  return (
    // `h-full min-h-0` matches the settings panel next to it: the rail is the
    // same height as the content area, and the menu list is the only part that
    // scrolls. `shrink-0` used to be here to protect the width in a flex parent;
    // the parent is a grid now, where it does nothing. The right edge is the
    // rail's own ceramic seam, so the panel beside it needs no border of its own.
    <aside className="ceramic-rail ceramic-seam-r flex h-full min-h-0 w-16 flex-col overflow-hidden md:w-[303px]">
      <header className="px-2 pt-5 md:px-4 md:pt-5">
        {/* The account block sits in its own relief capsule, so the rail reads as
            a canvas with a card on it rather than as one flat slab. */}
        <h1 className="ceramic-relief flex items-center justify-center gap-2.5 rounded-full px-2 py-2 font-normal md:justify-start md:px-3">
          {/* The account mark, not the account's first letter: an uploaded picture
              still wins, and without one the slot shows a person glyph. */}
          <CardIdentityIcon
            kind="user"
            avatar={userInfo?.avatar}
            data-testid="account-identity"
          />

          <div className="hidden min-w-0 flex-col items-start gap-1 md:flex">
            <p className="text-sm text-text-primary truncate">
              {userInfo?.email}
            </p>
            {/* The rail is narrow, so the role sits under the address rather
                than beside it; the flex/gap wrapper keeps it aligned with the
                email column. */}
            <div className="flex items-center gap-2">
              <RoleTag role={userInfo?.role} />
            </div>
          </div>
        </h1>
      </header>

      <nav className="min-h-0 flex-1 overflow-auto mt-4 py-1">
        <ul className="px-2 md:px-6 flex flex-col gap-2 md:gap-5 items-center md:items-stretch">
          {menuItems(t).map((item) => {
            const { key, icon, label, ...rest } = item;

            return (
              <li key={key} className="w-full md:w-auto">
                <Button
                  {...rest}
                  block
                  variant="ghost"
                  aria-label={label}
                  className={cn(
                    // 40px row on the shared rail; the ceramic block and the brand
                    // edge mark the current page, the pointer frosts the rest.
                    'ceramic-nav-item relative h-10 text-base max-md:size-10 max-md:p-0 max-md:justify-center justify-start gap-2.5 px-2 md:px-3',
                    activeItemKey === key && 'ceramic-nav-item-active',
                  )}
                  onClick={handleMenuClick(key)}
                >
                  <span className="flex items-center gap-2.5 max-md:gap-0">
                    {icon}
                    <span className="hidden md:inline">{label}</span>
                  </span>
                </Button>
              </li>
            );
          })}
        </ul>
      </nav>

      <footer className="p-2 md:p-6 mt-auto">
        <div className="hidden md:flex items-center gap-2 mb-6 justify-between">
          <span className="text-xs text-accent-primary">{version}</span>

          <ThemeSwitch />
        </div>

        <Button
          block
          size="lg"
          variant="transparent"
          aria-label={t('setting.logout')}
          // Outline ceramic capsule: the relief reads as a raised control, the
          // ink turns to the error colour under the pointer.
          className="ceramic-relief h-10 rounded-full text-text-secondary hover:text-state-error max-md:size-10 max-md:p-0 max-md:mx-auto max-md:justify-center"
          onClick={() => logout()}
        >
          <LucideLogOut className="size-[1em] md:hidden" />
          <span className="hidden md:inline">{t('setting.logout')}</span>
        </Button>
      </footer>
    </aside>
  );
}
