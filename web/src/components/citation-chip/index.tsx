import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';
import { useCallback } from 'react';

/**
 * A citation marker in an answer body: `[1]`.
 *
 * The marker has to read as something the reader can act on. It previously
 * rendered as secondary-coloured text on a card background two RGB units off the
 * page (`rgb(160,166,175)` on `rgb(29,32,37)`), with `cursor: auto` and no
 * handler — visually indistinguishable from the prose around it, so a working
 * hover card went unnoticed: it opens on Radix's 700 ms default delay, and
 * nothing about the marker suggested hovering it was worth doing.
 *
 * So: the accent token every other link in the app uses, a pointer cursor, a
 * hover state that fills in, a 100 ms open delay, and a click that opens the
 * passage the marker points at (the same target the popover's document button
 * opens).
 */
export default function CitationChip({
  index,
  onOpen,
  children,
}: {
  /** 0-based pool index; displayed 1-based, the way the backend numbered it. */
  index: number;
  onOpen?: () => void;
  children?: React.ReactNode;
}) {
  const handleOpen = useCallback(() => {
    onOpen?.();
  }, [onOpen]);

  return (
    <HoverCard openDelay={100} closeDelay={80}>
      <HoverCardTrigger asChild>
        <button
          type="button"
          onClick={handleOpen}
          className="text-accent-primary bg-accent-color-soft rounded-2xl px-1 mx-1 text-nowrap inline-block align-baseline cursor-pointer transition-colors hover:bg-accent-primary hover:text-text-primary-inverse focus-visible:ring-2 focus-visible:ring-cable-accent"
        >
          <bdi>[{index + 1}]</bdi>
        </button>
      </HoverCardTrigger>
      <HoverCardContent className="max-w-3xl">{children}</HoverCardContent>
    </HoverCard>
  );
}
