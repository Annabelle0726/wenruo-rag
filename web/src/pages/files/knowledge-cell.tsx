import { Button } from '@/components/ui/button';

import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from '@/components/ui/hover-card';
import { IFile } from '@/interfaces/database/file-manager';
import { Ellipsis } from 'lucide-react';
import { useCallback } from 'react';

/**
 * The knowledge-base cell. A file linked to knowledge bases gets one themed
 * capsule per base; an unlinked file renders nothing, so the column stays quiet
 * instead of repeating a placeholder down every row.
 */
export function KnowledgeCell({ value }: { value: IFile['kbs_info'] }) {
  const renderBadges = useCallback((list: IFile['kbs_info'] = []) => {
    return list.map((x) => (
      <span
        key={x.kb_id}
        className="inline-flex shrink-0 items-center rounded-full border border-cable-border-hover bg-cable-nav-active-bg px-2.5 py-0.5 text-xs text-cable-accent"
      >
        {x.kb_name}
      </span>
    ));
  }, []);

  if (!Array.isArray(value) || !value.length) {
    return null;
  }

  return (
    <section className="flex gap-2 items-center">
      {renderBadges(value?.slice(0, 2))}

      {value.length > 2 && (
        <HoverCard>
          <HoverCardTrigger>
            <Button variant={'ghost'} size={'sm'}>
              <Ellipsis />
            </Button>
          </HoverCardTrigger>
          <HoverCardContent className="flex gap-2 flex-wrap">
            {renderBadges(value)}
          </HoverCardContent>
        </HoverCard>
      )}
    </section>
  );
}
