import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useLocalStorageState } from 'ahooks';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useTranslation } from 'react-i18next';

import {
  PanelLeftClose,
  PanelLeftOpen,
  ChevronRight,
  LucideBookText,
  LucideFolderOpen,
  LucideLogs,
  LucideSettings,
  LucideTextSearch,
} from 'lucide-react';

import { DatasetIdentityMark } from '@/components/dataset-category';
import { Button } from '@/components/ui/button';
import { useSecondPathName } from '@/hooks/route-hook';
import { cn, formatBytes } from '@/lib/utils';
import { Routes } from '@/routes';
import { formatPureDate } from '@/utils/date';

import { IDataset } from '@/interfaces/database/dataset';
import { useLocation, useParams } from 'react-router';

type DatasetSidebarItem = {
  icon: ReactNode;
  label: string;
  key: string;
  children?: { id: string; label: string }[];
};

type PropType = {
  refreshCount?: number;
  dataset: IDataset;
};

export function SideBar({ dataset: data }: PropType) {
  const [collapsed, setCollapsed] = useLocalStorageState<boolean>(
    'dataset_sidebar_collapsed',
    { defaultValue: false },
  );
  const toggleCollapsed = useCallback(
    () => setCollapsed((value) => !value),
    [setCollapsed],
  );
  const pathName = useSecondPathName();
  const { id } = useParams();
  const { pathname } = useLocation();
  const { t } = useTranslation();
  const isConfigurationActive = '/' + pathName === Routes.DataSetSetting;
  const [configurationExpanded, setConfigurationExpanded] = useState(
    isConfigurationActive,
  );

  useEffect(() => {
    if (isConfigurationActive) {
      setConfigurationExpanded(true);
    }
  }, [isConfigurationActive]);

  const items = useMemo<DatasetSidebarItem[]>(() => {
    const list: DatasetSidebarItem[] = [
      {
        icon: <LucideFolderOpen className="size-4" />,
        label: t(`knowledgeDetails.subbarFiles`),
        key: Routes.Files,
      },
      {
        icon: <LucideTextSearch className="size-4" />,
        label: t(`knowledgeDetails.testing`),
        key: Routes.DatasetTesting,
      },
      {
        icon: <LucideLogs className="size-4" />,
        label: t(`knowledgeDetails.overview`),
        key: Routes.DataSetOverview,
      },
      {
        icon: <LucideSettings className="size-4" />,
        label: t(`knowledgeDetails.configuration`),
        key: Routes.DataSetSetting,
        children: [
          {
            id: 'basic-info',
            label: t('knowledgeConfiguration.baseInfo'),
          },
          {
            id: 'visibility',
            label: t('knowledgeConfiguration.visibilitySettings'),
          },
          {
            id: 'retrieval',
            label: t('knowledgeConfiguration.retrievalSettings'),
          },
          {
            id: 'parsing',
            label: t('knowledgeConfiguration.parsingMethod'),
          },
        ],
      },
      {
        icon: <LucideBookText className="size-4" />,
        label: t('knowledgeDetails.artifacts'),
        key: Routes.Compilation,
      },
    ];

    return list;
  }, [t]);

  return (
    <aside
      className={cn(
        'flex h-full shrink-0 flex-col relative min-h-0 overflow-hidden transition-[width] duration-200 ease-in-out motion-reduce:transition-none',
        /* `w-56`, not `w-64`: the expanded rail was 256px of a 1280px content
           column and spent a fifth of the page on a five-item menu. 224px still
           holds the longest label plus its 16px icon and the submenu chevron, keeps
           the name, the file count and the created date on their own lines
           untruncated, and gives the log table's region 32px back. The COLLAPSED
           branch is untouched: its 64px box, the centred 48px toggle and the
           centred icons are the same geometry they were, and only one of the two
           widths is ever in the DOM. */
        collapsed ? 'w-16' : 'w-56',
      )}
      data-collapsed={Boolean(collapsed)}
    >
      <header className="shrink-0 ps-0 pe-0 pb-3">
        <div
          className={cn(
            'flex min-w-0 items-center gap-2',
            collapsed && 'justify-center',
          )}
        >
          {!collapsed && data?.id && (
            <h3
              className="min-w-0 flex-1 truncate text-sm font-semibold text-text-primary"
              title={data.name}
            >
              {data.name}
            </h3>
          )}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className={cn(
                  'h-9 rounded-none p-0',
                  collapsed ? 'w-12 justify-center' : 'w-9 justify-center',
                )}
                onClick={toggleCollapsed}
                aria-expanded={!collapsed}
                aria-label={t(
                  collapsed
                    ? 'knowledgeDetails.expandSidebar'
                    : 'knowledgeDetails.collapseSidebar',
                )}
              >
                {collapsed ? (
                  <PanelLeftOpen className="size-4" />
                ) : (
                  <PanelLeftClose className="size-4" />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              {t(
                collapsed
                  ? 'knowledgeDetails.expandSidebar'
                  : 'knowledgeDetails.collapseSidebar',
              )}
            </TooltipContent>
          </Tooltip>
        </div>
        {/* The identity and its metadata arrive together with the knowledge base
            itself, in a row whose height is reserved from the first paint. Rendered
            before it does, this block read "undefined files" over an empty name and
            then rewrote itself as the list loaded; taking the space only when the
            data arrives moved the whole navigation area down by 48px instead.
            Reserved and then filled, the sidebar is settled on the first paint. */}
        {!collapsed && (
          <div className="mt-2 flex min-h-10 min-w-0 items-center gap-2">
            {data?.id && (
              <>
                <DatasetIdentityMark
                  dataset={data}
                  className="size-8 shrink-0"
                  iconClassName="size-4"
                />
                <div className="min-w-0 text-xs leading-5 text-text-secondary">
                  <div className="flex flex-wrap items-center gap-x-1">
                    <span>
                      {data.document_count} {t('knowledgeDetails.files')}
                    </span>
                    {data.size !== undefined && (
                      <>
                        <span aria-hidden="true">·</span>
                        <span>{formatBytes(data.size)}</span>
                      </>
                    )}
                  </div>
                  <div>
                    {t('knowledgeDetails.created')}{' '}
                    {formatPureDate(data.create_time)}
                  </div>
                </div>
              </>
            )}
          </div>
        )}
      </header>

      <nav
        className={cn(
          'min-h-0 flex-1 overflow-y-auto overscroll-contain scroll-smooth pt-1 pb-4',
          collapsed ? 'px-2' : 'ps-0 pe-3',
        )}
      >
        <ul className="space-y-1">
          {items.map((item) => {
            const active = '/' + pathName === item.key;
            const hasChildren = Boolean(item.children?.length);
            const expanded = hasChildren && !collapsed && configurationExpanded;

            return (
              <li key={item.key}>
                <div className="flex min-w-0 items-center gap-1">
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        aria-label={item.label}
                        aria-current={active ? 'page' : undefined}
                        asLink
                        block
                        variant="ghost"
                        className={cn(
                          'min-w-0 flex-1 justify-start gap-3 px-0 py-2 relative h-9 text-sm',
                          collapsed && 'justify-center',
                          active && 'bg-accent-primary-5 text-accent-primary',
                        )}
                        to={
                          hasChildren
                            ? `${Routes.DatasetBase}${item.key}/${id}/basic-info`
                            : `${Routes.DatasetBase}${item.key}/${id}`
                        }
                      >
                        {item.icon}
                        {!collapsed && (
                          <span className="truncate">{item.label}</span>
                        )}
                      </Button>
                    </TooltipTrigger>
                    {collapsed && (
                      <TooltipContent side="right">{item.label}</TooltipContent>
                    )}
                  </Tooltip>
                  {!collapsed && hasChildren && (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={t('setting.toggleSection', {
                        section: item.label,
                      })}
                      aria-expanded={expanded}
                      aria-controls="dataset-settings-subnav"
                      className="size-6 shrink-0 p-0 text-text-secondary hover:text-accent-primary"
                      onClick={() =>
                        setConfigurationExpanded((value) => !value)
                      }
                      data-testid="dataset-settings-nav-toggle"
                    >
                      <ChevronRight
                        className={cn(
                          'size-3.5 transition-transform',
                          expanded && 'rotate-90',
                        )}
                      />
                    </Button>
                  )}
                </div>
                {expanded && (
                  <ul
                    id="dataset-settings-subnav"
                    className="ms-3.5 mt-0.5 flex flex-col gap-0.5 border-s border-accent-primary/25 ps-2"
                    data-testid="dataset-settings-subnav"
                  >
                    {item.children?.map((child) => {
                      const selected = pathname.endsWith(`/${child.id}`);
                      return (
                        <li key={child.id}>
                          <Button
                            asLink
                            block
                            variant="ghost"
                            aria-current={selected ? 'location' : undefined}
                            className={cn(
                              'settings-rail-child w-full justify-start',
                              selected &&
                                'bg-accent-primary-5 font-medium text-accent-primary',
                            )}
                            to={`${Routes.DatasetBase}${Routes.DataSetSetting}/${id}/${child.id}`}
                          >
                            <span className="truncate">{child.label}</span>
                          </Button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      </nav>
    </aside>
  );
}
