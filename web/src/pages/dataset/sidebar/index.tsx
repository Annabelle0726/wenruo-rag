import { useCallback, useMemo } from 'react';
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
import { useParams } from 'react-router';

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
  const { t } = useTranslation();

  const items = useMemo(() => {
    const list = [
      {
        icon: <LucideFolderOpen className="size-[1em]" />,
        label: t(`knowledgeDetails.subbarFiles`),
        key: Routes.Files,
      },
      {
        icon: <LucideTextSearch className="size-[1em]" />,
        label: t(`knowledgeDetails.testing`),
        key: Routes.DatasetTesting,
      },
      {
        icon: <LucideLogs className="size-[1em]" />,
        label: t(`knowledgeDetails.overview`),
        key: Routes.DataSetOverview,
      },
      {
        icon: <LucideSettings className="size-[1em]" />,
        label: t(`knowledgeDetails.configuration`),
        key: Routes.DataSetSetting,
      },
      {
        icon: <LucideBookText className="size-[1em]" />,
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
        collapsed ? 'w-16' : 'w-64',
      )}
      data-collapsed={Boolean(collapsed)}
    >
      <header className="shrink-0 px-3 pb-3">
        <div className="flex min-w-0 items-center justify-end gap-2">
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
                className="shrink-0"
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
          collapsed ? 'px-2' : 'px-3',
        )}
      >
        <ul className="space-y-1">
          {items.map((item) => {
            const active = '/' + pathName === item.key;

            return (
              <li key={item.key}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      aria-label={item.label}
                      aria-current={active ? 'page' : undefined}
                      asLink
                      block
                      variant="ghost"
                      className={cn(
                        'justify-start gap-2 px-2 py-2 relative h-9 text-sm',
                        collapsed && 'justify-center px-0',
                        active && 'bg-bg-card text-text-primary',
                      )}
                      to={`${Routes.DatasetBase}${item.key}/${id}`}
                    >
                      {item.icon}
                      {!collapsed && <span>{item.label}</span>}
                    </Button>
                  </TooltipTrigger>
                  {collapsed && (
                    <TooltipContent side="right">{item.label}</TooltipContent>
                  )}
                </Tooltip>
              </li>
            );
          })}
        </ul>
      </nav>
    </aside>
  );
}
