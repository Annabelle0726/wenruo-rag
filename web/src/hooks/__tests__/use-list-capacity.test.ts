import { readRegionCapacity } from '@/hooks/use-list-capacity';

/**
 * How many complete items a list region holds, read off the region itself.
 *
 * jsdom does no layout, so the geometry is declared here - but what is being
 * pinned is the reading of it: which numbers come from the region (columns from
 * its resolved tracks, the height from its box) and that a partial row never
 * counts. The real geometry is verified in a browser.
 */
const layout = (el: HTMLElement, height: number, width = 1200) => {
  Object.defineProperty(el, 'clientHeight', { configurable: true, value: height });
  Object.defineProperty(el, 'clientWidth', { configurable: true, value: width });
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
}: {
  regionHeight: number;
  rowHeight: number;
  headerHeight: number;
  rows: number;
}) => {
  const region = document.createElement('div');
  region.setAttribute('data-list-region', '');
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
    expect(readRegionCapacity(cardGrid({ tracks, regionHeight: 689, cardHeight: 112 }))).toBe(20);
    expect(readRegionCapacity(cardGrid({ tracks, regionHeight: 557, cardHeight: 112 }))).toBe(16);
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
});
