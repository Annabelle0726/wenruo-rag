import { usePublishBreadcrumbTrail } from '@/layouts/components/breadcrumb-context';
import { Routes } from '@/routes';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Outlet, useLocation } from 'react-router';
import { SideBar } from './sidebar';

/**
 * The settings rail's own tabs, in the order it lists them. Keyed by the route
 * constant the rail navigates to, so the crumb and the highlighted tab cannot
 * drift apart; the labels are the same keys the rail renders.
 */
const SectionLabelKeys: Record<string, string> = {
  [Routes.Model]: 'setting.model',
  [Routes.DataSource]: 'setting.dataSources',
  [Routes.Team]: 'setting.team',
  [Routes.Usage]: 'setting.usageOperations',
  [Routes.Profile]: 'setting.profile',
  [Routes.Api]: 'setting.api',
};

function UserSetting() {
  const { pathname } = useLocation();
  const { t } = useTranslation();

  /**
   * 用户设置 > 当前 Tab.
   *
   * The tab is the second path segment — the same rule the rail uses to highlight
   * one of its own entries, rather than a second copy of the state. A sub-page that
   * is not a rail tab (a data-source detail, a chat channel) publishes nothing and
   * leaves the crumb at 用户设置 on its own.
   */
  const trail = useMemo(() => {
    const section = `/${pathname.split('/')[2] ?? ''}`;
    const labelKey = SectionLabelKeys[section];

    return labelKey ? [{ label: t(labelKey) }] : [];
  }, [pathname, t]);

  usePublishBreadcrumbTrail(trail);

  return (
    // Fills exactly what the app shell leaves below the header, because `main`
    // in the shell is the `1fr` row that is left once the bar is laid out.
    // `min-h-0` on the section and on the content column is what keeps each
    // column's own scroll area scrolling: grid items are `min-height: auto` by
    // default, so a tall child used to stretch the section past the screen and
    // push both the panel's footer and its content out of the viewport instead
    // of scrolling inside it.
    //
    // The content column carries no padding of its own: the panel inside it is
    // meant to sit flush against the rail, the right edge and the bottom edge,
    // which is what its header and body then pad for themselves.
    <section className="grid size-full min-h-0 min-w-0 grid-cols-[4rem_minmax(0,1fr)] grid-rows-1 md:grid-cols-[303px_minmax(0,1fr)]">
      <SideBar />

      <div className="flex min-h-0 min-w-0 flex-1">
        <Outlet />
      </div>
    </section>
  );
}

export default UserSetting;
