import { useFetchKnowledgeBaseConfiguration } from '@/hooks/use-knowledge-request';
import { usePublishBreadcrumbTrail } from '@/layouts/components/breadcrumb-context';
import { KnowledgeBaseProvider } from '@/pages/dataset/contexts/knowledge-base-context';
import { Routes } from '@/routes';
import { TABLE_ROW_PITCH_PX } from '@/utils/list-capacity';
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
      <article className="page-gutter pt-3 size-full grid grid-cols-[auto_minmax(0,1fr)]
      grid-rows-1 gap-1">
        <SideBar dataset={data} />

        {/* The shell's region, for the sub-pages that do not mark one of their
            own: this is the box the shell gives the page (one viewport minus the
            header and the breadcrumb bar). A sub-page that owns a tighter box for
            its list marks that box too and the INNERMOST region is the one that
            decides the page size - the files view does, because this box also
            carries the page's own header, toolbar and bulk bar, whose heights are
            not the list's.

            The declared item height is the app's table row pitch, used only until
            a real row has rendered - after that the row itself is measured. */}
        <div
          className="min-w-0 min-h-0 overflow-auto"
          data-list-region=""
          data-list-item-height={TABLE_ROW_PITCH_PX}
        >
          <Outlet />
        </div>
      </article>
    </KnowledgeBaseProvider>
  );
}
