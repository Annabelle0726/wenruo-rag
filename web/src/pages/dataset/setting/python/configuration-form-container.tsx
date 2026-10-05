import { cn } from '@/lib/utils';
import { PropsWithChildren, ReactNode } from 'react';

type ConfigurationSectionProps = PropsWithChildren & {
  className?: string;
  /**
   * The section's own heading. Optional so a caller that has nothing to name (a
   * variant with a single unnamed group) still gets the same surface.
   */
  title?: ReactNode;
  /** One line, never a paragraph: `text-xs` keeps it under the fields it labels. */
  description?: ReactNode;
};

/**
 * One configuration section: a hairline frame, one step of the neutral surface and
 * a 2px brand marker on its heading.
 *
 * The parser page is four groups of settings read top to bottom, so each group is a
 * surface of its own instead of one long plane of fields. The frame is
 * `--border-default` and the fill is `--bg-card` - the same quiet card the rest of
 * the Dataset area uses, one step off the page's `--bg-base` - and the brand green
 * appears only as the marker, the hover/focus border and the controls that are
 * already green. The only transition is colour: a surface that answered the pointer
 * by moving would make a form of a hundred fields twitch.
 */
export function ConfigurationFormContainer({
  children,
  className,
  title,
  description,
}: ConfigurationSectionProps) {
  return (
    <section
      className={cn(
        'rounded-lg border border-border-default bg-bg-card',
        'transition-colors duration-150 ease-out',
        'hover:border-accent-primary/25 focus-within:border-accent-primary/40',
        className,
      )}
    >
      {title && (
        <header className="flex items-start gap-3 border-b border-border-default px-5 py-3.5">
          <span
            className="mt-0.5 h-5 w-1 shrink-0 rounded-full bg-accent-primary"
            aria-hidden="true"
          />
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-text-primary">
              {title}
            </h2>
            {description && (
              <p className="mt-0.5 text-xs leading-5 text-text-secondary">
                {description}
              </p>
            )}
          </div>
        </header>
      )}

      <div className="space-y-4 px-5 py-5">{children}</div>
    </section>
  );
}

/** The column the sections stack in. */
export function MainContainer({
  children,
  className,
}: PropsWithChildren & { className?: string }) {
  return <div className={cn('flex flex-col gap-4', className)}>{children}</div>;
}
