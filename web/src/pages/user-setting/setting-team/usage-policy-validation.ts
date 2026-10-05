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

/**
 * The Usage Policy form's pure logic.
 *
 * It is separate from the component because these are the rules a reviewer has to
 * be able to read and a test has to be able to pin: which fields an edit touches,
 * what counts as a valid value, and which fields a save actually sends. The
 * component then only owns state and rendering.
 *
 * The bounds MIRROR THE STORAGE COLUMNS, not a product opinion: `calls_*` live in
 * an IntegerField and `tokens_*` in a BigIntegerField, so the backend refuses
 * anything else and the form must refuse it before the round trip.
 */

export const CALL_MAX = 2_147_483_647;
export const TOKEN_MAX = 10_000_000_000;

/** The four limits a NORMAL member's policy is made of. */
export const POLICY_LIMIT_FIELDS = [
  'calls_per_day',
  'calls_per_month',
  'tokens_per_day',
  'tokens_per_month',
] as const;

export type PolicyLimitField = (typeof POLICY_LIMIT_FIELDS)[number];

export const POLICY_FIELD_LABEL_KEYS: Record<PolicyLimitField, string> = {
  calls_per_day: 'usage.limitCallsPerDay',
  calls_per_month: 'usage.limitCallsPerMonth',
  tokens_per_day: 'usage.limitTokensPerDay',
  tokens_per_month: 'usage.limitTokensPerMonth',
};

/** What the form shows when a field has no draft: the confirmed value, as text. */
export type PolicyDraft = Record<PolicyLimitField, string>;

export const draftFromLimits = (
  limits: Record<string, number> | undefined,
): PolicyDraft =>
  POLICY_LIMIT_FIELDS.reduce<PolicyDraft>((accumulator, field) => {
    accumulator[field] = String(limits?.[field] ?? '');
    return accumulator;
  }, {} as PolicyDraft);

export type PolicyFieldError = 'empty' | 'notInteger' | 'belowMin' | 'aboveMax';

export interface IPolicyFieldValidation {
  ok: boolean;
  /** The integer to submit, present only when `ok`. */
  value?: number;
  error?: PolicyFieldError;
}

/**
 * Validates one field the way the backend will.
 *
 * A BLANK field is `empty` and never 0: the design is explicit that clearing an
 * input is not a way to express "not enforced", because a silently submitted 0
 * on a call dimension is refused and a silently submitted 0 on a token dimension
 * would silently disable a limit. A token limit of 0 typed deliberately is valid
 * and means "not enforced".
 */
export const validatePolicyField = (
  field: PolicyLimitField,
  raw: string,
): IPolicyFieldValidation => {
  const text = (raw ?? '').trim();
  if (text === '') {
    return { ok: false, error: 'empty' };
  }
  // Integer syntax only: no sign, no decimal point, no exponent, no separators,
  // so "1e3", "0x10", "1,000" and "1.5" are refused rather than coerced.
  if (!/^\d+$/.test(text)) {
    return { ok: false, error: 'notInteger' };
  }
  const value = Number(text);
  if (!Number.isSafeInteger(value)) {
    return { ok: false, error: 'notInteger' };
  }
  const min = field.startsWith('calls') ? 1 : 0;
  if (value < min) {
    return { ok: false, error: 'belowMin' };
  }
  const max = field.startsWith('calls') ? CALL_MAX : TOKEN_MAX;
  if (value > max) {
    return { ok: false, error: 'aboveMax' };
  }
  return { ok: true, value };
};

/**
 * The fields an edit actually changes.
 *
 * A field whose draft equals the confirmed baseline is NOT sent, so saving the
 * daily call limit cannot rewrite the monthly token limit or the timezone. An
 * unchanged form produces an empty patch, and the caller must then send nothing
 * at all rather than an empty body the server would refuse.
 */
export const buildPolicyPatch = (
  baseline: PolicyDraft,
  draft: PolicyDraft,
): Partial<Record<PolicyLimitField, number>> => {
  const patch: Partial<Record<PolicyLimitField, number>> = {};
  POLICY_LIMIT_FIELDS.forEach((field) => {
    if (draft[field] === baseline[field]) {
      return;
    }
    const validation = validatePolicyField(field, draft[field]);
    if (validation.ok && validation.value !== undefined) {
      patch[field] = validation.value;
    }
  });
  return patch;
};

export const isDraftDirty = (baseline: PolicyDraft, draft: PolicyDraft): boolean =>
  POLICY_LIMIT_FIELDS.some((field) => draft[field] !== baseline[field]);

/** Every field-level error of a draft, keyed by field. */
export const collectPolicyErrors = (
  draft: PolicyDraft,
  baseline: PolicyDraft,
): Partial<Record<PolicyLimitField, PolicyFieldError>> => {
  const errors: Partial<Record<PolicyLimitField, PolicyFieldError>> = {};
  POLICY_LIMIT_FIELDS.forEach((field) => {
    if (draft[field] === baseline[field]) {
      return;
    }
    const validation = validatePolicyField(field, draft[field]);
    if (!validation.ok && validation.error) {
      errors[field] = validation.error;
    }
  });
  return errors;
};

/**
 * The `If-Match` conflict the server answers with.
 *
 * The server reports it as HTTP 200 + `code=101` + `error_type=POLICY_CONFLICT`,
 * so a caller that only checks for a failed HTTP status would treat a refused
 * write as a saved one. This is the single place that reads the distinction.
 */
export const isPolicyConflict = (body: any): boolean =>
  body?.code === 101 && body?.data?.error_type === 'POLICY_CONFLICT';

export const isSuccess = (body: any): boolean => body?.code === 0;
