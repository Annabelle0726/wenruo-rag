import { useFetchKnowledgeBaseConfiguration } from '@/hooks/use-knowledge-request';
import { usePublishBreadcrumbTrail } from '@/layouts/components/breadcrumb-context';
import { KnowledgeBaseProvider } from '@/pages/dataset/contexts/knowledge-base-context';
import { Routes } from '@/routes';
import { useMemo } from 'react';

import { Outlet, useParams } from 'react-router';
import { SideBar } from './sidebar';

export default function DatasetWrapper() {
  const { data, loading } = useFetchKnowledgeBaseConfiguration();
  const { id } = useParams();

  // The knowledge base's name is the second level of the global breadcrumb, and
  // the page that fetches it is the only place that already holds it: the bar sits
  // above this route and cannot reach `KnowledgeBaseProvider`. The link points at
  // the files view — this knowledge base's main view — so the level is a real
  // parent rather than the bare `/dataset` shell, which renders nothing on its own.
  const trail = useMemo(
    () =>
      data?.name && id
        ? [
            {
              label: data.name,
              to: `${Routes.DatasetBase}${Routes.Files}/${id}`,
            },
          ]
        : [],
    [data?.name, id],
  );

  usePublishBreadcrumbTrail(trail);

  return (
    <KnowledgeBaseProvider knowledgeBase={data} loading={loading}>
      <article className="pt-3 size-full grid grid-cols-[auto_minmax(0,1fr)] grid-rows-1">
        <SideBar dataset={data} />

        {/* The region a dataset page's list pages by: this is the box the shell
            gives the page (one viewport minus the header and the breadcrumb bar),
            so it is the one place that knows how many rows fit. The declared item
            height is the document table's own row height (`h-[38px]` in
            `dataset/dataset/dataset-table.tsx`), used only until its first real row
            has rendered - after that the row itself is measured. */}
        <div
          className="min-w-0 min-h-0 overflow-auto"
          data-list-region=""
          data-list-item-height="38"
        >
          <Outlet />
        </div>
      </article>
    </KnowledgeBaseProvider>
  );
}
