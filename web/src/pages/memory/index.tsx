import Spotlight from '@/components/spotlight';
import { usePublishBreadcrumbTrail } from '@/layouts/components/breadcrumb-context';
import { Routes } from '@/routes';
import { useMemo } from 'react';
import { Outlet, useParams } from 'react-router';
import { useFetchMemoryBaseConfiguration } from './hooks/use-memory-setting';
import { SideBar } from './sidebar';

export default function DatasetWrapper() {
  const { data } = useFetchMemoryBaseConfiguration();
  const { id } = useParams();

  // 记忆 > 名称 > 子页面. The name comes from the same query the sidebar reads, so
  // React Query serves both from one request. The link returns to the memory's own
  // messages view, dropping whichever sub-page was open.
  const trail = useMemo(
    () =>
      data?.name && id
        ? [
            {
              label: data.name,
              to: `${Routes.Memory}/${Routes.MemoryMessage}/${id}`,
            },
          ]
        : [],
    [data?.name, id],
  );

  usePublishBreadcrumbTrail(trail);

  return (
    <section className="flex h-full flex-col w-full pt-3">
      <div className="flex flex-1 min-h-0">
        <SideBar></SideBar>
        <div className=" relative flex-1 overflow-auto border-[0.5px] border-border-button p-5 rounded-md mr-5 mb-5">
          <Spotlight />
          <Outlet />
        </div>
      </div>
    </section>
  );
}
