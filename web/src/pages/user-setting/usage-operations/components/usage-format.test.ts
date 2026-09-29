/*
 *  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 */

import {
  formatCount,
  formatMicrosAsUsd,
  resolveCostDisplay,
  resolveDayWindow,
} from './usage-format';

describe('cost rendering honours "unestablished is not zero"', () => {
  it('reports an unpriced scope as unavailable rather than $0.00', () => {
    // The live deployment is 0 PRICED / 75 UNPRICED, so this is the main path.
    expect(resolveCostDisplay(null, 'unavailable')).toEqual({
      kind: 'unavailable',
      micros: null,
      usd: null,
    });
    expect(resolveCostDisplay(0, 'unavailable')).toEqual({
      kind: 'unavailable',
      micros: null,
      usd: null,
    });
  });

  it('treats an absent figure as unavailable whatever the coverage says', () => {
    expect(resolveCostDisplay(undefined, 'complete').kind).toBe('unavailable');
    expect(resolveCostDisplay(null, undefined).kind).toBe('unavailable');
  });

  it('labels a mixed scope partial while still showing the real sum', () => {
    expect(resolveCostDisplay(700, 'partial')).toEqual({
      kind: 'partial',
      micros: 700,
      usd: '$0.0007',
    });
  });

  it('shows an established figure as a value', () => {
    expect(resolveCostDisplay(1_500_000, 'complete')).toEqual({
      kind: 'value',
      micros: 1_500_000,
      usd: '$1.50',
    });
  });

  it('never produces the string $0.00 for a missing price', () => {
    const displays = [
      resolveCostDisplay(null, 'unavailable'),
      resolveCostDisplay(null, 'partial'),
      resolveCostDisplay(undefined, undefined),
    ];
    displays.forEach((display) => {
      expect(display.usd).toBeNull();
    });
  });
});

describe('micro-USD formatting keeps a real but tiny cost visible', () => {
  it('keeps six decimals below one cent', () => {
    expect(formatMicrosAsUsd(3)).toBe('$0.000003');
    expect(formatMicrosAsUsd(700)).toBe('$0.0007');
  });

  it('uses two decimals from one cent upwards', () => {
    expect(formatMicrosAsUsd(10_000)).toBe('$0.01');
    expect(formatMicrosAsUsd(500_000)).toBe('$0.50');
    expect(formatMicrosAsUsd(42_500_000)).toBe('$42.50');
  });

  it('formats exact integer counts without rounding them away', () => {
    expect(formatCount(1_615_894)).toBe('1,615,894');
    expect(formatCount(0)).toBe('0');
    expect(formatCount(null)).toBe('-');
  });
});

describe('the day window is always bounded', () => {
  it('returns an inclusive window of the requested length', () => {
    expect(resolveDayWindow(7, '2026-03-10')).toEqual({
      start_day: '2026-03-04',
      end_day: '2026-03-10',
    });
  });

  it('spans a month boundary correctly', () => {
    expect(resolveDayWindow(31, '2026-03-01')).toEqual({
      start_day: '2026-01-30',
      end_day: '2026-03-01',
    });
  });

  it('stays inside the server cap of 92 days', () => {
    const window = resolveDayWindow(92, '2026-03-10');
    const days =
      (new Date(`${window.end_day}T00:00:00Z`).getTime() -
        new Date(`${window.start_day}T00:00:00Z`).getTime()) /
      86_400_000 +
      1;
    expect(days).toBe(92);
  });
});
