import { useLayoutEffect, useRef, useState } from 'react';

/**
 * The chrome between the three measured pieces: four 12px flex gaps inside the
 * 56px bar, plus the 1px brand/nav rail, plus 3px of slack. Counting it here is
 * what keeps the compact breakpoint from firing late and letting the nav clip.
 */
const LAYOUT_GAP = 52;
const FIT_BUFFER = 16;

export function useHeaderNavLayout(measureKey = '') {
  const headerRef = useRef<HTMLElement>(null);
  const logoRef = useRef<HTMLDivElement>(null);
  const expandedRightMeasureRef = useRef<HTMLDivElement>(null);
  const navMeasureRef = useRef<HTMLDivElement>(null);
  const [isCompact, setIsCompact] = useState(true);

  useLayoutEffect(() => {
    const measure = () => {
      const header = headerRef.current;
      const logo = logoRef.current;
      const expandedRight = expandedRightMeasureRef.current;
      const nav = navMeasureRef.current;

      if (!header || !logo || !expandedRight || !nav) {
        return;
      }

      // `clientWidth` includes the bar's own `page-gutter` padding (16–48px per
      // side depending on the breakpoint), and that padding is not space the nav
      // can use. Reading it off the computed style is what makes the breakpoint
      // correct at every width instead of ~96px late on a desktop viewport.
      const styles = window.getComputedStyle(header);
      const contentWidth =
        header.clientWidth -
        parseFloat(styles.paddingLeft) -
        parseFloat(styles.paddingRight);

      const navWidth = nav.scrollWidth;
      const availableForDesktop =
        contentWidth - logo.offsetWidth - expandedRight.offsetWidth - LAYOUT_GAP;

      setIsCompact(navWidth + FIT_BUFFER > availableForDesktop);
    };

    measure();

    const observer = new ResizeObserver(measure);
    [
      headerRef.current,
      logoRef.current,
      expandedRightMeasureRef.current,
      navMeasureRef.current,
    ].forEach((node) => {
      if (node) {
        observer.observe(node);
      }
    });

    return () => observer.disconnect();
  }, [measureKey]);

  return {
    headerRef,
    logoRef,
    expandedRightMeasureRef,
    navMeasureRef,
    isCompact,
  };
}
