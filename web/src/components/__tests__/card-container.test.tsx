import { CardContainer } from '@/components/card-container';
import { render } from '@testing-library/react';

/**
 * The card grid's column count is a layout contract, not decoration.
 *
 * `grid-cols-1 md:grid-cols-2 lg:grid-cols-3` stopped adding columns at 1024px, so
 * an 11-card list was four rows tall on a 1920px-wide window — 520px of cards in
 * the ~418px a 1366x768 laptop actually leaves for the card area, which is what
 * pushed the last row out of sight. jsdom does no layout, so these pin the parts
 * of the contract that are checkable here; the geometry itself is verified in a
 * real browser.
 */
describe('CardContainer', () => {
  const gridOf = (container: HTMLElement) => container.firstElementChild as HTMLElement;

  const renderGrid = (children: React.ReactNode) =>
    render(<CardContainer>{children}</CardContainer>);

  it('sizes its columns from the space it is given instead of from breakpoints', () => {
    const grid = gridOf(renderGrid(<div />).container);

    // A width-driven track list, so a wider window means more cards per row.
    expect(grid.className).toContain('auto-fill');
    expect(grid.className).toContain('minmax(');
    expect(grid.className).toContain('17rem');
    // No breakpoint column counts: those are what stopped at three.
    expect(grid.className).not.toMatch(/(^|\s)(md|lg|xl|2xl|sm):grid-cols-/);
    expect(grid.className).not.toMatch(/(^|\s)grid-cols-\d/);
  });

  it('keeps the row gap tighter than the column gap', () => {
    const grid = gridOf(renderGrid(<div />).container);

    expect(grid.className).toContain('gap-x-6');
    expect(grid.className).toContain('gap-y-4');
    expect(grid.className).not.toMatch(/(^|\s)gap-6(\s|$)/);
  });

  it('renders only the cards it is handed', () => {
    // The grid used to append `col-span-full h-6` as an extra child. That is a
    // real grid row, not breathing room: it cost its own height plus a row gap,
    // which was the last ~48px of scroll height between an 11-card list and
    // fitting on a laptop viewport without scrolling.
    const grid = gridOf(
      renderGrid(
        <>
          <div data-testid="a" />
          <div data-testid="b" />
        </>,
      ).container,
    );

    expect(grid.children).toHaveLength(2);
    expect(grid.querySelector('[aria-hidden="true"]')).toBeNull();
  });

  it('starts its rows at the top and still reserves the scrollbar gutter', () => {
    const grid = gridOf(renderGrid(<div />).container);

    // `content-start` is what keeps a short list from stretching its cards, and
    // the reserved gutter is what stops the columns jumping sideways when a page
    // change adds or removes the grid's own scrollbar.
    expect(grid.className).toContain('content-start');
    expect(grid.className).toContain('scrollbar-gutter-stable');
  });

  it('marks itself as the grid the page size is measured from', () => {
    const grid = gridOf(renderGrid(<div />).container);

    // `useFittingPageSize` finds the grid through this attribute to work out how
    // many cards one page should ask for, so losing it silently brings back the
    // scrollbar the fitted default removes.
    expect(grid.getAttribute('data-card-grid')).toBe('');
  });
});
