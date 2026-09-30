import {
  getListCapacitySnapshot,
  readRegionCapacity,
  subscribeListCapacity,
} from '@/hooks/use-list-capacity';

/**
 * How many complete items a list region holds, read off the region itself.
 *
 * jsdom does no layout, so the geometry is declared here - but what is being
 * pinned is the reading of it: which numbers come from the region (columns from
 * its resolved tracks, the height from its box) and that a partial row never
 * counts. The real geometry is verified in a browser.
 */
const layout = (el: HTMLElement, height: number, width = 1200) => {
  Object.defineProperty(el, 'clientHeight', {
    configurable: true,
    value: height,
  });
  Object.defineProperty(el, 'clientWidth', {
    configurable: true,
    value: width,
  });
  el.getBoundingClientRect = () =>
    ({
      width,
      height,
      top: 0,
      left: 0,
      right: width,
      bottom: height,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    }) as DOMRect;
};

const cardGrid = ({
  tracks,
  regionHeight,
  cardHeight,
  rowGap = '16px',
  cards = 4,
  withCard = true,
}: {
  tracks: string;
  regionHeight: number;
  cardHeight: number;
  rowGap?: string;
  cards?: number;
  withCard?: boolean;
}) => {
  const region = document.createElement('div');
  region.setAttribute('data-list-region', '');
  region.style.display = 'grid';
  region.style.gridTemplateColumns = tracks;
  region.style.rowGap = rowGap;
  region.style.setProperty('--list-card-height', `${cardHeight}px`);
  document.body.appendChild(region);
  layout(region, regionHeight);
  if (withCard) {
    Array.from({ length: cards }).forEach(() => {
      const card = document.createElement('div');
      region.appendChild(card);
      layout(card, cardHeight, 275);
    });
  }
  return region;
};

const table = ({
  regionHeight,
  rowHeight,
  headerHeight,
  rows,
  declaredHeight,
  placeholderRows = 0,
  footerHeight = 0,
  nested,
}: {
  regionHeight: number;
  rowHeight: number;
  headerHeight: number;
  rows: number;
  /** `data-list-item-height`, the row height the region states about itself. */
  declaredHeight?: number;
  /** Rows that are not data (`data-skeleton`), e.g. a skeleton or an empty state. */
  placeholderRows?: number;
  footerHeight?: number;
  /** A tighter region nested inside this one. */
  nested?: HTMLElement;
}) => {
  const region = document.createElement('div');
  region.setAttribute('data-list-region', '');
  if (declaredHeight) {
    region.setAttribute('data-list-item-height', String(declaredHeight));
  }
  document.body.appendChild(region);
  layout(region, regionHeight);
  const tableEl = document.createElement('table');
  const thead = document.createElement('thead');
  const headRow = document.createElement('tr');
  thead.appendChild(headRow);
  const tbody = document.createElement('tbody');
  tableEl.append(thead, tbody);
  region.appendChild(tableEl);
  // The measurement subtracts the header the table renders, which is the `thead`.
  layout(thead, headerHeight);
  layout(headRow, headerHeight);
  Array.from({ length: rows }).forEach(() => {
    const row = document.createElement('tr');
    tbody.appendChild(row);
    layout(row, rowHeight);
  });
  Array.from({ length: placeholderRows }).forEach(() => {
    const row = document.createElement('tr');
    row.setAttribute('data-skeleton', '');
    tbody.appendChild(row);
    layout(row, 96);
  });
  if (footerHeight) {
    const footer = document.createElement('div');
    footer.setAttribute('data-list-footer', '');
    region.appendChild(footer);
    layout(footer, footerHeight);
  }
  if (nested) region.appendChild(nested);
  return region;
};

afterEach(() => {
  document.body.innerHTML = '';
});

describe('card grid capacity', () => {
  it('reads the columns off the grid and the rows off its height', () => {
    const region = cardGrid({
      tracks: '275.5px 275.5px 275.5px 275.5px',
      regionHeight: 446,
      cardHeight: 112,
    });

    // 4 columns x 3 complete rows.
    expect(readRegionCapacity(region)).toBe(12);
  });

  it('measures a region whose data has not arrived yet', () => {
    // The whole point: the region is on screen before the cards are, and the
    // row height comes from the shared token the card is built from - so the
    // first request already asks for 12 rather than fetching a default page.
    const region = cardGrid({
      tracks: '275.5px 275.5px 275.5px 275.5px',
      regionHeight: 446,
      cardHeight: 112,
      withCard: false,
    });

    expect(readRegionCapacity(region)).toBe(12);
  });

  it('grows and shrinks with the region', () => {
    const tracks = '275.5px 275.5px 275.5px 275.5px';
    expect(
      readRegionCapacity(
        cardGrid({ tracks, regionHeight: 689, cardHeight: 112 }),
      ),
    ).toBe(20);
    expect(
      readRegionCapacity(
        cardGrid({ tracks, regionHeight: 557, cardHeight: 112 }),
      ),
    ).toBe(16);
    // 1024px wide: three tracks.
    expect(
      readRegionCapacity(
        cardGrid({
          tracks: '300px 300px 300px',
          regionHeight: 557,
          cardHeight: 112,
        }),
      ),
    ).toBe(12);
  });

  it('gives up rather than guessing without a region', () => {
    expect(readRegionCapacity(null)).toBeNull();
  });
});

describe('table capacity', () => {
  it('counts complete body rows under the header', () => {
    // 600px region, 40px header, 38px rows: 14 complete rows.
    expect(
      readRegionCapacity(
        table({ regionHeight: 600, rowHeight: 38, headerHeight: 40, rows: 6 }),
      ),
    ).toBe(14);
  });

  it('does not count a row that would be cut', () => {
    expect(
      readRegionCapacity(
        table({ regionHeight: 600, rowHeight: 38, headerHeight: 40, rows: 6 }),
      ),
    ).toBe(Math.floor((600 - 40) / 38));
  });

  it('has no opinion while the table has no rows to measure', () => {
    expect(
      readRegionCapacity(
        table({ regionHeight: 600, rowHeight: 38, headerHeight: 40, rows: 0 }),
      ),
    ).toBeNull();
  });

  it('pages by the row height the region declares, before any row exists', () => {
    // The declaration is the table's own contract (`h-[38px]` rows with no
    // vertical cell padding), and reading it is what lets the FIRST request be a
    // whole page: without it the page fetches a default and corrects itself, which
    // is one visible jump in the count for every visit.
    expect(
      readRegionCapacity(
        table({
          regionHeight: 600,
          rowHeight: 38,
          headerHeight: 40,
          rows: 0,
          declaredHeight: 38,
        }),
      ),
    ).toBe(Math.floor((600 - 40) / 38));
  });

  it('does not page by a row that is not data', () => {
    // An empty state or a loading skeleton is 96px against a 38px row. Measured,
    // it pages the table by a third of what it can show - and it does so exactly
    // while the list is empty, which is the reading that then sticks.
    expect(
      readRegionCapacity(
        table({
          regionHeight: 600,
          rowHeight: 38,
          headerHeight: 40,
          rows: 4,
          placeholderRows: 1,
        }),
      ),
    ).toBe(Math.floor((600 - 40) / 38));

    expect(
      readRegionCapacity(
        table({
          regionHeight: 600,
          rowHeight: 38,
          headerHeight: 40,
          rows: 0,
          placeholderRows: 1,
          declaredHeight: 38,
        }),
      ),
    ).toBe(Math.floor((600 - 40) / 38));
  });

  it('never lets a live row lower the declared height', () => {
    // A row taller than the contract is a layout fact the capacity has to respect
    // (otherwise the region scrolls); a row SHORTER than it is not evidence that
    // more rows fit, which is the direction that made the page size follow the
    // rows it had produced.
    const taller = readRegionCapacity(
      table({
        regionHeight: 600,
        rowHeight: 48,
        headerHeight: 40,
        rows: 3,
        declaredHeight: 38,
      }),
    );
    expect(taller).toBe(Math.floor((600 - 40) / 48));

    const shorter = readRegionCapacity(
      table({
        regionHeight: 600,
        rowHeight: 30,
        headerHeight: 40,
        rows: 3,
        declaredHeight: 38,
      }),
    );
    expect(shorter).toBe(Math.floor((600 - 40) / 38));
  });

  it('subtracts the marked footer from the space the rows have', () => {
    // The pager is a flex sibling inside the same region. Counted as row space it
    // is a row the region cannot show, so the page asks for rows the pager covers.
    expect(
      readRegionCapacity(
        table({
          regionHeight: 600,
          rowHeight: 38,
          headerHeight: 40,
          rows: 4,
          footerHeight: 52,
        }),
      ),
    ).toBe(Math.floor((600 - 40 - 52) / 38));
  });
});

describe('the shared capacity store', () => {
  const resizeObservers = { created: 0, observing: 0 };
  class FakeResizeObserver {
    observe() {
      resizeObservers.observing += 1;
    }
    disconnect() {
      resizeObservers.observing -= 1;
    }
    unobserve() {}
    constructor() {
      resizeObservers.created += 1;
    }
  }

  let unsubscribe: (() => void) | undefined;

  beforeEach(() => {
    resizeObservers.created = 0;
    resizeObservers.observing = 0;
    (globalThis as Record<string, unknown>).ResizeObserver = FakeResizeObserver;
  });

  afterEach(() => {
    unsubscribe?.();
    unsubscribe = undefined;
  });

  it('publishes the innermost marked region', () => {
    // A page shell marks the box the shell gives the page and the list inside
    // marks the tighter box it pages by. The tighter one is the answer: the outer
    // box also carries the page's own header, toolbar and bulk bar, so measuring
    // it made the page size move when a row was merely selected.
    const inner = table({
      regionHeight: 600,
      rowHeight: 38,
      headerHeight: 40,
      rows: 4,
      declaredHeight: 38,
    });
    const outer = table({
      regionHeight: 600,
      rowHeight: 38,
      headerHeight: 40,
      rows: 4,
      nested: inner,
    });

    unsubscribe = subscribeListCapacity(() => {});

    expect(getListCapacitySnapshot()).toBe(Math.floor((600 - 40) / 38));
    // The outer region is a region too, just not the one that owns the page size.
    expect(outer.getAttribute('data-list-capacity')).toBeNull();
    expect(inner.dataset.listCapacity).toBe(
      String(Math.floor((600 - 40) / 38)),
    );
  });

  it('measures once for every hook on the page', () => {
    // Several hooks on one paginated page each need this number. When each of them
    // owned an observer, a single sidebar toggle produced several competing
    // readings - and several refetches.
    table({
      regionHeight: 600,
      rowHeight: 38,
      headerHeight: 40,
      rows: 4,
      declaredHeight: 38,
    });

    const first = subscribeListCapacity(() => {});
    const second = subscribeListCapacity(() => {});
    const third = subscribeListCapacity(() => {});

    expect(resizeObservers.created).toBe(1);
    expect(resizeObservers.observing).toBe(1);

    third();
    second();
    expect(resizeObservers.observing).toBe(1);
    first();
    expect(resizeObservers.observing).toBe(0);
  });

  it('has no capacity for a page whose list has no region', () => {
    unsubscribe = subscribeListCapacity(() => {});

    expect(getListCapacitySnapshot()).toBeNull();
  });
});
