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

import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { useFetchProviderIncidents } from '@/hooks/use-provider-health-request';
import { useListTenant } from '@/hooks/use-user-setting-request';
import { IWorkspaceNotification } from '@/interfaces/notification';
import { cn } from '@/lib/utils';
import { TenantRole } from '@/pages/user-setting/constants';
import { Routes } from '@/routes';
import { providerIncidentNotifications } from '@/utils/provider-incident';
import { BellRing } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import {
  selectNotifications,
  selectUnreadCount,
  useNotificationStore,
} from './notification-store';

/**
 * The two real notification sources this release has.
 *
 * A workspace invitation the caller has not answered yet is an operational fact
 * the server already reports on `GET /tenants`, and the header already used it to
 * decorate the bell. A provider incident is the other one, and it comes from the
 * SAME read the Provider Health page uses - the drawer holds no provider-health
 * state model of its own, sums no occurrences and reclassifies no error.
 *
 * Nothing else is constructed: a category whose backend source does not exist
 * (usage thresholds, retrieval health) produces NO entry rather than a placeholder.
 */
const useInvitationNotifications = (): IWorkspaceNotification[] => {
  const { data: tenants } = useListTenant();

  return useMemo(
    () =>
      (tenants ?? [])
        .filter((tenant) => tenant.role === TenantRole.Invite)
        .map((tenant) => ({
          id: `workspace-invitation:${tenant.tenant_id}`,
          category: 'SYSTEM_WARNING' as const,
          severity: 'info' as const,
          titleKey: 'notification.workspaceInvitationTitle',
          descriptionKey: 'notification.workspaceInvitationDescription',
          params: { workspace: tenant.name ?? tenant.nickname ?? '' },
          createdAt: tenant.update_date || undefined,
          readAt: null,
          route: Routes.ProfileTeam,
          source: 'workspace_invitation' as const,
        })),
    [tenants],
  );
};

const formatRelativeTime = (value: string | undefined, locale: string) => {
  if (!value) {
    return null;
  }
  // `update_date` arrives as a plain `YYYY-MM-DD HH:mm:ss` string; the space
  // separator is not ISO, and Safari refuses it. Normalising it here is a parse
  // fix, not an invented time - an unparseable value renders no time at all.
  const parsed = new Date(value.replace(' ', 'T'));
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  const diffSeconds = Math.round((Date.now() - parsed.getTime()) / 1000);
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
  const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ['second', 60],
    ['minute', 60],
    ['hour', 24],
    ['day', 30],
    ['month', 12],
    ['year', Number.POSITIVE_INFINITY],
  ];
  let amount = Math.abs(diffSeconds);
  for (const [unit, span] of units) {
    if (amount < span) {
      return formatter.format(Math.sign(diffSeconds) * -amount, unit);
    }
    amount = Math.floor(amount / span);
  }
  return null;
};

function NotificationEntry({
  notification,
  onOpen,
  onMarkRead,
}: {
  notification: IWorkspaceNotification;
  onOpen: (notification: IWorkspaceNotification) => void;
  onMarkRead: (id: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const relative = formatRelativeTime(
    notification.createdAt,
    i18n.resolvedLanguage ?? 'en',
  );

  return (
    <li
      className={cn(
        'ceramic-relief flex flex-col gap-1 rounded-[2px] p-3',
        notification.readAt ? 'opacity-70' : undefined,
      )}
      data-testid="notification-entry"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-text-primary">
          {t(notification.titleKey, notification.params)}
        </p>
        {!notification.readAt && (
          <span
            className="mt-1 size-2 shrink-0 rounded-[50%] bg-state-warning"
            aria-label={t('notification.unread')}
          />
        )}
      </div>
      {notification.descriptionText ? (
        <p className="text-xs text-text-secondary">
          {notification.descriptionText}
        </p>
      ) : (
        notification.descriptionKey && (
          <p className="text-xs text-text-secondary">
            {t(notification.descriptionKey, notification.params)}
          </p>
        )
      )}
      {notification.metaKey && (
        <p className="text-xs text-text-secondary">
          {t(notification.metaKey, notification.metaParams)}
        </p>
      )}
      {/* No timestamp is rendered when the record does not carry one. */}
      {relative && <p className="text-xs text-text-disabled">{relative}</p>}
      <div className="flex items-center gap-2 pt-1">
        {notification.route && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => onOpen(notification)}
          >
            {t('notification.open')}
          </Button>
        )}
        {!notification.readAt && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => onMarkRead(notification.id)}
          >
            {t('notification.markAsRead')}
          </Button>
        )}
      </div>
    </li>
  );
}

/**
 * The navigation bell: icon, unread badge and the notification drawer.
 *
 * The badge shows a COUNT and is hidden at zero, matching the three documented
 * bell states (no unread / dot / number). The drawer is honest about its own
 * emptiness: with no notification it says so and names what will feed it, rather
 * than showing example events.
 */
export function NotificationCenter({ className }: { className?: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const notifications = useNotificationStore(selectNotifications);
  const unreadCount = useNotificationStore(selectUnreadCount);
  const syncSource = useNotificationStore((state) => state.syncSource);
  const markRead = useNotificationStore((state) => state.markRead);
  const markAllRead = useNotificationStore((state) => state.markAllRead);
  const invitations = useInvitationNotifications();
  const { data: providerHealth, refetch: refetchProviderHealth } =
    useFetchProviderIncidents();
  const translate = useCallback((key: string) => t(key), [t]);
  const incidents = useMemo(
    () =>
      providerIncidentNotifications(
        providerHealth,
        translate,
        `${Routes.UserSetting}${Routes.Usage}/provider-health`,
      ),
    [providerHealth, translate],
  );

  useEffect(() => {
    syncSource('workspace_invitation', invitations);
  }, [invitations, syncSource]);

  useEffect(() => {
    syncSource('provider_incident', incidents);
  }, [incidents, syncSource]);

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (next) {
      // Opening the drawer is the refresh trigger - not a timer. A failed read
      // leaves the entries as they are; it never empties them.
      void refetchProviderHealth();
    }
  };

  const handleOpen = (notification: IWorkspaceNotification) => {
    markRead(notification.id, new Date().toISOString());
    setOpen(false);
    if (notification.route) {
      navigate(notification.route);
    }
  };

  const handleMarkRead = (id: string) => {
    markRead(id, new Date().toISOString());
  };

  const handleMarkAllRead = () => {
    markAllRead(new Date().toISOString());
  };

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <Button
        variant="ghost"
        size="icon"
        className={cn('relative size-8 shrink-0 p-0', className)}
        aria-label={t('notification.openDrawer')}
        onClick={() => handleOpenChange(true)}
        data-testid="notification-bell"
      >
        <BellRing className="size-[1.05rem]" />
        {unreadCount > 0 && (
          <span
            className="absolute -end-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-state-error px-1 text-[10px] leading-none text-text-primary-inverse"
            data-testid="notification-badge"
          >
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </Button>

      <SheetContent side="right" className="flex w-full flex-col gap-4 sm:max-w-md">
        <SheetHeader>
          <SheetTitle className="text-base">
            {t('notification.title')}
          </SheetTitle>
          <SheetDescription className="text-xs">
            {t('notification.deliveryScope')}
          </SheetDescription>
        </SheetHeader>

        <div className="flex items-center justify-between">
          <span className="text-xs text-text-secondary">
            {t('notification.unreadCount', { count: unreadCount })}
          </span>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            disabled={unreadCount === 0}
            onClick={handleMarkAllRead}
          >
            {t('notification.markAllAsRead')}
          </Button>
        </div>

        <ScrollArea className="min-h-0 flex-1">
          {notifications.length === 0 ? (
            <div
              className="ceramic-relief flex flex-col gap-2 rounded-[2px] p-4"
              data-testid="notification-empty"
            >
              <p className="text-sm text-text-primary">
                {t('notification.emptyTitle')}
              </p>
              <p className="text-xs text-text-secondary">
                {t('notification.emptyDescription')}
              </p>
            </div>
          ) : (
            <ul className="flex flex-col gap-2 pe-2">
              {notifications.map((notification) => (
                <NotificationEntry
                  key={notification.id}
                  notification={notification}
                  onOpen={handleOpen}
                  onMarkRead={handleMarkRead}
                />
              ))}
            </ul>
          )}
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}

export default NotificationCenter;
