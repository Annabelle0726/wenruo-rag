import { useCallback, useLayoutEffect, useRef, useState } from 'react';

// Elements that flag a validation error: the control marked by FormControl or
// the message paragraph rendered by FormMessage.
const ErrorIndicatorSelector =
  '[aria-invalid="true"], [id$="-form-item-message"]';

/**
 * Reveals validation errors after an invalid submit: expands every collapsed
 * settings section and scrolls the first error into view. The signal counter
 * re-triggers the layout effect on every invalid submit, even when the
 * sections are already open.
 *
 * The sections are the drawer's accordion items, so both the list of ids and
 * the ones open at first are supplied by the caller.
 */
export function useRevealSubmitErrors(
  sectionIds: readonly string[],
  initiallyOpenSections: readonly string[] = [],
) {
  const [openSections, setOpenSections] = useState<string[]>([
    ...initiallyOpenSections,
  ]);
  const [invalidSubmitSignal, setInvalidSubmitSignal] = useState(0);
  const formContainerRef = useRef<HTMLFormElement>(null);

  const handleInvalidSubmit = useCallback(() => {
    // Every section opens, otherwise the offending control can be hidden inside
    // a collapsed one and the error would be scrolled to but never seen.
    setOpenSections([...sectionIds]);
    setInvalidSubmitSignal((signal) => signal + 1);
  }, [sectionIds]);

  useLayoutEffect(() => {
    if (invalidSubmitSignal === 0) {
      return;
    }
    const firstErrorIndicator =
      formContainerRef.current?.querySelector<HTMLElement>(
        ErrorIndicatorSelector,
      );
    firstErrorIndicator?.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
    });
  }, [invalidSubmitSignal]);

  return {
    formContainerRef,
    handleInvalidSubmit,
    openSections,
    onOpenSectionsChange: setOpenSections,
  };
}
