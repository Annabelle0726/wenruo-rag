import { CardContainer } from '@/components/card-container';
import { HomeIcon } from '@/components/svg-icon';
import { PropsWithChildren, ReactNode } from 'react';

/**
 * Home page card grid. It is the shared `CardContainer`, so a home section and the
 * list page it previews render their cards in the same grid: same columns, same
 * row height, therefore the same card. Kept as a named alias because the two home
 * sections read better as "the home grid" than as a bare container.
 */
export function HomeCardGrid({
  children,
  className,
}: PropsWithChildren<{ className?: string }>) {
  return <CardContainer className={className}>{children}</CardContainer>;
}

type SectionHeadingProps = {
  iconName: string;
  label: string;
  children?: ReactNode;
};

/**
 * Section header: a square green indicator bar, the section icon in a 1px-bordered
 * tile and the title, plus an optional right-hand control slot. No gradient, no
 * halo, no rounded tile — the bar and the tile are the only marks.
 */
export function SectionHeading({
  iconName,
  label,
  children,
}: SectionHeadingProps) {
  return (
    <header className="mb-3 flex min-w-0 items-center justify-between gap-4 border-b border-panel-border pb-2">
      <h2 className="flex min-w-0 items-center gap-2 text-base font-semibold text-text-primary">
        <span aria-hidden className="h-4 w-1 shrink-0 bg-cable-brand" />
        <span className="flex size-6 shrink-0 items-center justify-center border border-panel-border bg-cable-icon text-cable-icon-foreground">
          <HomeIcon name={iconName} width={14} />
        </span>
        <span className="truncate">{label}</span>
      </h2>
      {children}
    </header>
  );
}
