import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { t } from 'i18next';
import { ChevronRight } from 'lucide-react';

/**
 * Shell for the see-all tile that closes a home card grid. A see-all tile is the
 * only tile that is not a card, so it is the only thing left here: the real cards
 * are the ones their list page renders, and the grid's equal rows size this tile
 * to them.
 */
const applicationCardClass = cn(
  // `card-interactive` supplies the pointer cursor and the colour-only hover
  // tint — no translate: the overflow-auto grid these tiles live in would clip
  // a lifted card, so the lift is the ceramic shadow instead.
  'card-interactive group h-full w-full rounded-xl px-4 py-3',
  // Translucent glass tint, matching the knowledge-base cards, so the page's
  // glow reads through the tile instead of stopping at an opaque surface. The
  // ceramic shell adds the inner rim light and the drop shadow per theme.
  'border border-cable-hairline bg-glass shadow-ceramic',
  'hover:border-ceramic-border-hover hover:shadow-ceramic-hover',
  'transition-[background-color,border-color,box-shadow,opacity] duration-200 ease-in-out',
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cable-accent',
);

export type SeeAllAppCardProps = {
  click(): void;
};

export function SeeAllAppCard({ click }: SeeAllAppCardProps) {
  return (
    <Card
      className={cn(
        applicationCardClass,
        // The same fixed size as a card, so the tile that closes a grid is never
        // the odd one out in its row.
        'flex h-[112px] items-center justify-center',
      )}
      onClick={click}
      tabIndex={0}
    >
      <CardContent className="flex w-full items-center justify-center gap-1.5 p-0 text-cable-muted transition-colors group-hover:text-cable-brand">
        {t('common.seeAll')} <ChevronRight className="size-4" />
      </CardContent>
    </Card>
  );
}
