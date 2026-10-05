import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation } from 'react-router';

import {
  LucideBot,
  LucideBrain,
  LucideDatabase,
  LucideFolderOpen,
  LucideHouse,
  LucideMenu,
  LucideMessagesSquare,
  LucideSearch,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui/sheet';
import { cn } from '@/lib/utils';
import { Routes } from '@/routes';
import { BrandLockup } from './brand-lockup';
import { DatasetNavMenu } from './dataset-nav-menu';

const PathMap = {
  [Routes.Datasets]: [Routes.Datasets, Routes.DatasetBase],
  [Routes.Chats]: [Routes.Chats, Routes.Chat],
  [Routes.Searches]: [Routes.Searches, Routes.Search],
  [Routes.Agents]: [Routes.Agents, Routes.AgentTemplates],
  [Routes.Memories]: [Routes.Memories, Routes.Memory, Routes.MemoryMessage],
  [Routes.Files]: [Routes.Files],
} as const;

// Match on path-segment boundaries, not a loose substring, so e.g.
// "/user-setting/chat-channel" does not match the "/chat" tab.
const matchesPath = (pathname: string, candidate: string) =>
  pathname === candidate || pathname.startsWith(`${candidate}/`);

// Every tab carries an icon: a bare text row reads as a list of links, while an
// icon + label pair reads as navigation and is recognisable at a glance.
const menuItems = [
  { path: Routes.Root, name: 'header.home', icon: LucideHouse },
  {
    path: Routes.Datasets,
    name: 'header.dataset',
    icon: LucideDatabase,
    'data-testid': 'nav-dataset',
  },
  {
    path: Routes.Chats,
    name: 'header.chat',
    icon: LucideMessagesSquare,
    'data-testid': 'nav-chat',
  },
  {
    path: Routes.Searches,
    name: 'header.search',
    icon: LucideSearch,
    'data-testid': 'nav-search',
  },
  {
    path: Routes.Agents,
    name: 'header.flow',
    icon: LucideBot,
    'data-testid': 'nav-agent',
  },
  {
    path: Routes.Memories,
    name: 'header.memories',
    icon: LucideBrain,
  },
  {
    path: Routes.Files,
    name: 'header.fileManager',
    icon: LucideFolderOpen,
  },
];

function useActivePath() {
  const { pathname } = useLocation();

  return useMemo(() => {
    return (
      Object.keys(PathMap).find((x: string) =>
        PathMap[x as keyof typeof PathMap].some((y: string) =>
          matchesPath(pathname, y),
        ),
      ) || pathname
    );
  }, [pathname]);
}

/**
 * One shape for every tab: icon and label on one line, the FULL height of the
 * 56px bar, with an 8px gap. Full-height tabs are what make the bar read as a tab
 * strip rather than a row of links: the selected item's 2px mint indicator lands
 * on the bar's own bottom edge instead of floating inside it, and the knowledge
 * base's popover (opened at `sideOffset: 0`) attaches flush to that same edge.
 *
 * The ink lives in the two component classes defined in `tailwind.css`, both of
 * which read the shared `--cable-nav-*` tokens: `gov-nav-link` is the idle state
 * with its hover wash, and `gov-nav-link-active` adds the wash plus the 2px
 * indicator line along the bottom edge. The header scopes those tokens to the
 * white scale, so the bar stays readable while the same tokens keep their
 * mid-grey values on the white pages below it.
 */
const desktopNavLinkClass = (isActive: boolean) =>
  cn(
    'gov-nav-link inline-flex h-14 items-center justify-center gap-2 whitespace-nowrap px-3 text-sm',
    isActive && 'gov-nav-link-active',
  );

export function DesktopNavbar() {
  const { t } = useTranslation();
  const activePath = useActivePath();

  return (
    <nav>
      <ul className="flex items-center gap-1">
        {menuItems.map(({ path, name, icon: Icon, ...props }) => {
          const isActive = path === activePath;

          return (
            <li key={path}>
              {path === Routes.Datasets ? (
                // The knowledge base carries the plant's own two-level menu:
                // classification, then that class's knowledge bases.
                <DatasetNavMenu
                  to={path}
                  label={t(name)}
                  icon={Icon}
                  isActive={isActive}
                  testId={props['data-testid']}
                  className={desktopNavLinkClass(isActive)}
                />
              ) : (
                <Link
                  {...props}
                  to={path}
                  className={desktopNavLinkClass(isActive)}
                  aria-current={isActive ? 'page' : undefined}
                >
                  <Icon className="size-4 shrink-0 stroke-[1.75]" />
                  <span>{t(name)}</span>
                </Link>
              )}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function MobileNavItem({
  label,
  icon: Icon,
  isActive,
  onClick,
  ...linkProps
}: {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  isActive?: boolean;
  onClick?: () => void;
  to: string;
  'data-testid'?: string;
}) {
  return (
    <Link
      {...linkProps}
      onClick={onClick}
      className={cn(
        'flex w-full items-center gap-3 px-4 py-3 text-sm',
        'text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary',
        'focus-visible:bg-surface-hover focus-visible:text-text-primary focus-visible:outline-none',
        isActive &&
          'border-l-2 border-l-cable-brand bg-cable-brand-soft font-semibold text-cable-brand',
      )}
      aria-current={isActive ? 'page' : undefined}
    >
      <Icon className="size-5 shrink-0 stroke-[1.75]" />
      <span className="truncate">{label}</span>
    </Link>
  );
}

type MobileNavbarProps = {
  renderFooter?: (close: () => void) => React.ReactNode;
};

export function MobileNavbar({ renderFooter }: MobileNavbarProps) {
  const { t } = useTranslation();
  const activePath = useActivePath();
  const [open, setOpen] = useState(false);

  const close = () => setOpen(false);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-10 shrink-0 p-0 text-white/85 hover:bg-gov-header-hover hover:text-white focus-visible:bg-gov-header-hover focus-visible:text-white"
          aria-label="Menu"
        >
          <LucideMenu className="size-6 stroke-[1.75]" />
        </Button>
      </SheetTrigger>

      <SheetContent
        side="left"
        closeIcon={false}
        className="flex w-[min(85vw,18rem)] flex-col gap-0 p-0 sm:w-72"
      >
        <div className="flex shrink-0 items-center justify-center gap-3 border-b border-panel-border bg-gov-header py-3">
          <BrandLockup />
          <span className="text-base font-semibold tracking-tight text-gov-header-fg">
            {t('header.brandShort')}
          </span>
        </div>

        <nav className="min-h-0 flex-1 overflow-y-auto py-2">
          <ul>
            {menuItems.map(({ path, name, icon, ...props }) => (
              <li key={path}>
                <MobileNavItem
                  {...props}
                  to={path}
                  label={t(name)}
                  icon={icon}
                  isActive={path === activePath}
                  onClick={close}
                />
              </li>
            ))}
          </ul>
        </nav>

        {renderFooter?.(close)}
      </SheetContent>
    </Sheet>
  );
}

const GlobalNavbar = DesktopNavbar;

export default GlobalNavbar;
