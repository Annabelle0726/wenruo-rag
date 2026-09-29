import {
  fittedPageSize,
  PAGE_SIZE_OPTIONS,
  readCardGridCapacity,
} from '@/hooks/use-fitting-page-size';

/**
 * The page size a list opens with is a layout decision: it must be small enough
 * that one page fits the card area, which is what stops the list pages arriving
 * with a scrollbar. jsdom does no layout, so the geometry is faked - but the
 * arithmetic that turns geometry into a request size is exactly what is being
 * pinned here, and the real geometry is verified in a browser.
 */
const layout = (
  el: HTMLElement,
  box: { width?: number; height?: number },
) => {
  Object.defineProperty(el, 'clientHeight', {
    configurable: true,
    value: box.height ?? 0,
  });
  Object.defineProperty(el, 'clientWidth', {
    configurable: true,
    value: box.width ?? 0,
  });
  el.getBoundingClientRect = () =>
    ({
      width: box.width ?? 0,
      height: box.height ?? 0,
      top: 0,
      left: 0,
      right: box.width ?? 0,
      bottom: box.height ?? 0,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    }) as DOMRect;
};

const grid = (options: {
  tracks: string;
  rowGap?: string;
  clientHeight: number;
  cards: number;
  cardHeight: number;
}) => {
  const el = document.createElement('div');
  el.style.gridTemplateColumns = options.tracks;
  el.style.rowGap = options.rowGap ?? '16px';
  document.body.appendChild(el);
  layout(el, { height: options.clientHeight, width: 1200 });
  Array.from({ length: options.cards }).forEach(() => {
    const card = document.createElement('div');
    el.appendChild(card);
    layout(card, { height: options.cardHeight, width: 275 });
  });
  return el;
};

afterEach(() => {
  document.body.innerHTML = '';
});

describe('card grid capacity', () => {
  it('multiplies the resolved columns by the rows that fit the height', () => {
    // 4 tracks, 446px of height, a 112px card and a 16px gap: three rows fit.
    const capacity = readCardGridCapacity(
      grid({
        tracks: '275.5px 275.5px 275.5px 275.5px',
        clientHeight: 446,
        cards: 13,
        cardHeight: 112,
      }),
    );

    expect(capacity).toBe(12);
  });

  it('follows the grid rather than a constant when the window is taller', () => {
    const capacity = readCardGridCapacity(
      grid({
        tracks: '275.5px 275.5px 275.5px 275.5px',
        clientHeight: 689,
        cards: 13,
        cardHeight: 112,
      }),
    );

    expect(capacity).toBe(20);
  });

  it('reads the column count off the grid, so a narrow window fits fewer', () => {
    const capacity = readCardGridCapacity(
      grid({
        tracks: '300px 300px 300px',
        clientHeight: 600,
        cards: 9,
        cardHeight: 112,
      }),
    );

    // 3 columns x 4 rows.
    expect(capacity).toBe(12);
  });

  it('gives up instead of guessing when there is nothing to measure', () => {
    const empty = grid({
      tracks: '275.5px 275.5px',
      clientHeight: 446,
      cards: 0,
      cardHeight: 0,
    });
    expect(readCardGridCapacity(empty)).toBeNull();
    expect(readCardGridCapacity(null)).toBeNull();
  });
});

describe('fitted page size', () => {
  it('snaps down to a size the pager can display', () => {
    // 12 cards fit but the control offers 10/20/50/100, and it can only render a
    // value it has an option for.
    expect(fittedPageSize(12)).toBe(10);
    expect(fittedPageSize(16)).toBe(10);
    expect(fittedPageSize(20)).toBe(20);
    expect(fittedPageSize(24)).toBe(20);
    expect(fittedPageSize(137)).toBe(100);
  });

  it('never returns more than the area can hold', () => {
    for (const capacity of [1, 9, 10, 19, 20, 49, 50, 99, 100, 400]) {
      const size = fittedPageSize(capacity);
      if (capacity >= Math.min(...PAGE_SIZE_OPTIONS)) {
        expect(size).toBeLessThanOrEqual(capacity);
      }
    }
  });

  it('keeps the smallest option when even that does not fit', () => {
    // A page that overflows beats one showing four cards.
    expect(fittedPageSize(4)).toBe(10);
    expect(fittedPageSize(9)).toBe(10);
  });

  it('has no opinion before the grid has been measured', () => {
    expect(fittedPageSize(null)).toBeUndefined();
    expect(fittedPageSize(0)).toBeUndefined();
  });
});
