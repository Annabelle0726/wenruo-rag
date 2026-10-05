import { usePublishBreadcrumbTrail } from '@/layouts/components/breadcrumb-context';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Outlet, useLocation } from 'react-router';
import { SideBar } from './sidebar';
import {
  buildSettingsNav,
  matchActiveChild,
  matchActiveSection,
} from './settings-nav';

function UserSetting() {
  const { pathname } = useLocation();
  const { t } = useTranslation();

  /**
   * 用户设置 > 分区 > 子页面.
   *
   * The trail is derived from the SAME navigation model the rail renders, so a
   * rename or a moved destination cannot leave the crumb pointing at a label the
   * rail no longer uses. The parent is published as soon as the path names a
   * section, and the child only when the path is one of its destinations - a
   * section's own page shows the parent alone rather than repeating it.
   */
  const trail = useMemo(() => {
    const sections = buildSettingsNav();
    const section = matchActiveSection(sections, pathname);

    if (!section) {
      return [];
    }

    const child = matchActiveChild(section, pathname);
    const items = [{ label: t(section.labelKey) }];
    if (child) {
      items.push({ label: t(child.labelKey) });
    }
    return items;
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
