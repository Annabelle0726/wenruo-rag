import {
  effectivePageSize,
  gridCapacity,
  MAX_PAGE_SIZE,
  pageAfterResize,
  pageSizeOptionsFor,
  rowsThatFit,
} from '@/utils/list-capacity';

/**
 * The page size a list asks for is a layout fact: the number of COMPLETE items
 * the page's own region can show, bounded by the user's own choice and by the
 * application cap. `50` is that cap - never the default number of records to
 * request - and the derived size is not snapped to whatever the size control
 * happened to offer.
 */
describe('rowsThatFit', () => {
  it('counts only complete rows', () => {
    // 446px of region, 112px cards, a 16px gap: three whole rows.
    expect(rowsThatFit(446, 112, 16)).toBe(3);
    // Four rows need 4 x 112 + 3 x 16 = 496px; one pixel less and the fourth row
    // is cut, so it belongs to the next page rather than half-showing here.
    expect(rowsThatFit(495, 112, 16)).toBe(3);
    expect(rowsThatFit(496, 112, 16)).toBe(4);
  });

  it('has no rows without a region or an item height', () => {
    expect(rowsThatFit(0, 112, 16)).toBe(0);
    expect(rowsThatFit(446, 0, 16)).toBe(0);
  });
});

describe('gridCapacity', () => {
  it('multiplies the columns by the complete rows', () => {
    expect(gridCapacity(4, 3)).toBe(12);
    expect(gridCapacity(4, 4)).toBe(16);
    expect(gridCapacity(3, 3)).toBe(9);
  });
});

describe('effectivePageSize', () => {
  it('uses the capacity, not a preset', () => {
    // A capacity of 12 must produce 12 - not 10 because the control knows 10,
    // and not 20 or 50 because those are "nicer" numbers.
    expect(effectivePageSize({ capacity: 12 })).toBe(12);
    expect(effectivePageSize({ capacity: 16 })).toBe(16);
    expect(effectivePageSize({ capacity: 24 })).toBe(24);
  });

  it('caps the capacity at the application maximum', () => {
    expect(effectivePageSize({ capacity: 60 })).toBe(MAX_PAGE_SIZE);
    expect(effectivePageSize({ capacity: 137 })).toBe(MAX_PAGE_SIZE);
  });

  it('treats the user selection as a maximum, not a mandate', () => {
    // Chosen 10, room for 12: honour the smaller number.
    expect(effectivePageSize({ capacity: 12, userCap: 10 })).toBe(10);
    // Remembered 50, room for 12: the viewport wins, because 50 complete cards
    // cannot be shown and pagination is what this page size is for.
    expect(effectivePageSize({ capacity: 12, userCap: 50 })).toBe(12);
    // Chosen 50 with room for 50: the user gets their 50.
    expect(effectivePageSize({ capacity: 50, userCap: 50 })).toBe(50);
  });

  it('never exceeds the application cap even when the user asks for more', () => {
    // effective = min(capacity, user maximum, application maximum), so a user
    // asking for 100 on a screen with room for 200 still gets the app's 50.
    expect(effectivePageSize({ capacity: 200, userCap: 100 })).toBe(
      MAX_PAGE_SIZE,
    );
    expect(effectivePageSize({ capacity: 200, userCap: 500 })).toBe(
      MAX_PAGE_SIZE,
    );
    // Below the cap, the user's own limit is what applies.
    expect(effectivePageSize({ capacity: 200, userCap: 30 })).toBe(30);
  });

  it('falls back to the cap it is allowed while the region is unmeasured', () => {
    expect(effectivePageSize({ capacity: null })).toBe(MAX_PAGE_SIZE);
    expect(effectivePageSize({ capacity: null, userCap: 20 })).toBe(20);
    expect(effectivePageSize({ capacity: 0, userCap: 20 })).toBe(20);
  });
});

describe('pageSizeOptionsFor', () => {
  it('offers the capacity alongside the presets that fit it', () => {
    expect(pageSizeOptionsFor(12)).toEqual([10, 12]);
    expect(pageSizeOptionsFor(16)).toEqual([10, 16]);
    expect(pageSizeOptionsFor(24)).toEqual([10, 20, 24]);
    expect(pageSizeOptionsFor(50)).toEqual([10, 20, 50]);
  });

  it('never offers a size the region could not show', () => {
    for (const capacity of [6, 9, 12, 15, 16, 24, 40, 50, 60]) {
      const offered = pageSizeOptionsFor(capacity);
      expect(offered).toContain(Math.min(capacity, MAX_PAGE_SIZE));
      for (const size of offered) {
        if (capacity >= 10) expect(size).toBeLessThanOrEqual(capacity);
        expect(size).toBeLessThanOrEqual(MAX_PAGE_SIZE);
      }
    }
  });

  it('keeps the presets when nothing has been measured', () => {
    expect(pageSizeOptionsFor(null)).toEqual([10, 20, 50, 100]);
  });
});

describe('pageAfterResize', () => {
  it('keeps the record the current page started at', () => {
    // Page 3 of 20 starts at record 41; with 12 per page that record is on
    // page 4. Keeping page 3 would silently jump back to record 25.
    expect(pageAfterResize({ page: 3, fromSize: 20, toSize: 12 })).toBe(4);
    // Page 1 stays page 1 whatever the size.
    expect(pageAfterResize({ page: 1, fromSize: 20, toSize: 12 })).toBe(1);
    // A bigger page keeps the same record on an earlier page.
    expect(pageAfterResize({ page: 4, fromSize: 12, toSize: 24 })).toBe(2);
  });

  it('is a no-op when the size did not change', () => {
    expect(pageAfterResize({ page: 5, fromSize: 12, toSize: 12 })).toBe(5);
  });

  it('is deterministic without a previous size', () => {
    expect(pageAfterResize({ page: 7, fromSize: null, toSize: 12 })).toBe(1);
  });
});
