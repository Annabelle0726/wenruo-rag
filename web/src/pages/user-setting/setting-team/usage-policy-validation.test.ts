/*
 *  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 */

import {
  buildPolicyPatch,
  CALL_MAX,
  collectPolicyErrors,
  draftFromLimits,
  isDraftDirty,
  isPolicyConflict,
  isSuccess,
  TOKEN_MAX,
  validatePolicyField,
} from './usage-policy-validation';

describe('policy field validation mirrors the storage columns', () => {
  it('accepts a positive call limit and refuses zero or negative', () => {
    expect(validatePolicyField('calls_per_day', '1')).toEqual({ ok: true, value: 1 });
    expect(validatePolicyField('calls_per_day', String(CALL_MAX))).toEqual({
      ok: true,
      value: CALL_MAX,
    });
    expect(validatePolicyField('calls_per_day', '0').error).toBe('belowMin');
    expect(validatePolicyField('calls_per_day', '-5').error).toBe('notInteger');
    expect(validatePolicyField('calls_per_day', String(CALL_MAX + 1)).error).toBe(
      'aboveMax',
    );
  });

  it('accepts 0 tokens as "not enforced" and refuses beyond the column', () => {
    expect(validatePolicyField('tokens_per_day', '0')).toEqual({
      ok: true,
      value: 0,
    });
    expect(validatePolicyField('tokens_per_month', String(TOKEN_MAX))).toEqual({
      ok: true,
      value: TOKEN_MAX,
    });
    expect(validatePolicyField('tokens_per_day', String(TOKEN_MAX + 1)).error).toBe(
      'aboveMax',
    );
  });

  it('never treats a blank field as 0', () => {
    expect(validatePolicyField('tokens_per_day', '').error).toBe('empty');
    expect(validatePolicyField('tokens_per_day', '   ').error).toBe('empty');
    expect(validatePolicyField('calls_per_day', '').error).toBe('empty');
  });

  it('refuses anything that is not an integer literal rather than coercing it', () => {
    ['1.5', '1e3', '0x10', '1,000', '٥', 'NaN', 'Infinity', '+3', '-5'].forEach(
      (value) => {
        expect(validatePolicyField('tokens_per_day', value).error).toBeDefined();
      },
    );
    // Surrounding whitespace is TRIMMED, not rejected: a pasted value routinely
    // arrives with a trailing space and refusing it would be pedantry, not safety.
    expect(validatePolicyField('tokens_per_day', ' 5 ')).toEqual({
      ok: true,
      value: 5,
    });
  });
});

describe('a save sends only what changed', () => {
  const baseline = draftFromLimits({
    calls_per_day: 100,
    calls_per_month: 1000,
    tokens_per_day: 0,
    tokens_per_month: 5000,
  });

  it('builds a patch from the dirty fields alone', () => {
    const draft = { ...baseline, calls_per_day: '250' };
    expect(buildPolicyPatch(baseline, draft)).toEqual({ calls_per_day: 250 });
  });

  it('sends nothing when nothing changed', () => {
    expect(buildPolicyPatch(baseline, { ...baseline })).toEqual({});
    expect(isDraftDirty(baseline, { ...baseline })).toBe(false);
  });

  it('omits an invalid edit instead of submitting it', () => {
    const draft = { ...baseline, tokens_per_day: '' };
    expect(buildPolicyPatch(baseline, draft)).toEqual({});
    expect(collectPolicyErrors(draft, baseline)).toEqual({ tokens_per_day: 'empty' });
  });

  it('reports the field that is out of range', () => {
    const draft = { ...baseline, calls_per_month: String(CALL_MAX + 1) };
    expect(collectPolicyErrors(draft, baseline)).toEqual({
      calls_per_month: 'aboveMax',
    });
    expect(buildPolicyPatch(baseline, draft)).toEqual({});
  });
});

describe('the conflict is read from the body, not from the HTTP status', () => {
  it('recognises POLICY_CONFLICT even though it arrives as HTTP 200', () => {
    expect(
      isPolicyConflict({ code: 101, data: { error_type: 'POLICY_CONFLICT' } }),
    ).toBe(true);
    expect(isSuccess({ code: 101, data: { error_type: 'POLICY_CONFLICT' } })).toBe(
      false,
    );
  });

  it('does not mistake a permission refusal or a success for a conflict', () => {
    expect(isPolicyConflict({ code: 108, message: 'no' })).toBe(false);
    expect(isPolicyConflict({ code: 0, data: {} })).toBe(false);
    expect(isSuccess({ code: 0, data: { calls_per_day: 5 } })).toBe(true);
  });
});
