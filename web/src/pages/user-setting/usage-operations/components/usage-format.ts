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

import { CostCoverage } from '@/interfaces/database/workspace-usage';

/** The ledger stores integer micro-USD, so no float ever reaches the UI. */
export const MICROS_PER_USD = 1_000_000;

export type CostDisplayKind = 'value' | 'partial' | 'unavailable';

export interface ICostDisplay {
  kind: CostDisplayKind;
  /** The exact stored value, or null when nothing is established. */
  micros: number | null;
  /** Formatted USD, or null when the value must not be shown. */
  usd: string | null;
}

/**
 * micro-USD -> a USD string.
 *
 * Sub-cent amounts keep six decimals so a real but tiny cost does not collapse
 * into `$0.00`; larger amounts keep two. Trailing zeros are trimmed only in the
 * high-precision case, so `$0.50` stays readable.
 */
export const formatMicrosAsUsd = (micros: number): string => {
  const usd = micros / MICROS_PER_USD;
  const absolute = Math.abs(usd);
  const highPrecision = absolute > 0 && absolute < 0.01;
  if (!highPrecision) {
    return `$${usd.toFixed(2)}`;
  }
  const text = usd
    .toFixed(6)
    .replace(/0+$/, '')
    .replace(/\.$/, '');
  return `$${text}`;
};

/**
 * Decides what a cost field may display.
 *
 * This is the single place the "never render `$0.00` for unpriced usage" rule is
 * enforced. A `null` figure means the server could NOT establish a cost - the
 * models carry no pricing, or a provider reported no usable token split - so the
 * only honest rendering is "Not available". A `partial` figure is a real, if
 * incomplete, sum and is labelled as partial rather than presented as the whole.
 */
export const resolveCostDisplay = (
  micros: number | null | undefined,
  coverage: CostCoverage | undefined,
): ICostDisplay => {
  if (coverage === 'unavailable' || micros === null || micros === undefined) {
    return { kind: 'unavailable', micros: null, usd: null };
  }
  const usd = formatMicrosAsUsd(micros);
  return { kind: coverage === 'partial' ? 'partial' : 'value', micros, usd };
};

const integerFormatter = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 0,
});

/** Tokens and call counts are shown EXACTLY - no "42.1M" rounding. */
export const formatCount = (value: number | null | undefined): string =>
  value === null || value === undefined
    ? '-'
    : integerFormatter.format(value);

/** Resolves a coverage string to its translation key. */
export const coverageLabelKey = (coverage: CostCoverage | undefined): string => {
  if (coverage === 'complete') {
    return 'usage.coverageComplete';
  }
  if (coverage === 'partial') {
    return 'usage.coveragePartial';
  }
  return 'usage.coverageUnavailable';
};

/**
 * The last `days` days as an inclusive `[start_day, end_day]` window.
 *
 * The window is always explicit and bounded: the server refuses a range longer
 * than 92 days, and this helper never asks for one.
 */
export const resolveDayWindow = (
  days: number,
  today: string,
): { start_day: string; end_day: string } => {
  const end = new Date(`${today}T00:00:00Z`);
  const start = new Date(end.getTime());
  start.setUTCDate(start.getUTCDate() - (days - 1));
  const iso = (value: Date) => value.toISOString().slice(0, 10);
  return { start_day: iso(start), end_day: iso(end) };
};
