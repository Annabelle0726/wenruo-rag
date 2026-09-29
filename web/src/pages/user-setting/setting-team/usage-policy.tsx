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

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { CardSkeleton } from '@/components/ui/skeleton';
import {
  useFetchQuotaStatus,
  useUpdateUsagePolicy,
} from '@/hooks/use-workspace-usage-request';
import { cn } from '@/lib/utils';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ComingDataPanel } from '../usage-operations/components/coming-data-panel';
import { LimitStandingList } from '../usage-operations/components/limit-standing-list';
import { ReadModelNotice } from '../usage-operations/components/read-model-notice';
import {
  buildPolicyPatch,
  collectPolicyErrors,
  draftFromLimits,
  isDraftDirty,
  isPolicyConflict,
  POLICY_FIELD_LABEL_KEYS,
  POLICY_LIMIT_FIELDS,
  PolicyDraft,
} from './usage-policy-validation';

type SaveOutcome = 'idle' | 'conflict' | 'unknown' | 'stale-after-save';

/**
 * Team > Usage policy: the four Calls/Tokens limits, editable.
 *
 * The state machine is the point of this component, and U3 §3.4 是它的规格:
 *
 * - a DRAFT is local text and never the effective limits. Editing cannot move the
 *   bars, the counters or any cached figure, and nothing is confirmed until the
 *   server answers `code=0` - HTTP 200 alone does NOT mean a write happened,
 *   because a conflict arrives as 200 with `code=101`;
 * - only fields that DIFFER from the confirmed baseline are submitted, so saving
 *   the daily call limit cannot rewrite the monthly token limit or the timezone;
 * - a conflict keeps the draft and demands an explicit reload-then-save; a
 *   timeout is an UNKNOWN result that is never retried automatically, because the
 *   write may already have landed;
 * - a save that succeeded but whose refresh failed says exactly that, instead of
 *   claiming the save failed or inviting a second submission.
 *
 * Reading stays where U1 put it: the same `/usage/quota` response, whose limits
 * are the enforcement path's own values. Nothing here re-derives a limit.
 */
export function UsagePolicySection({
  readOnly,
  roleResolved = true,
}: {
  readOnly: boolean;
  roleResolved?: boolean;
}) {
  const { t } = useTranslation();
  const { data: quota, loading, refetch, error } = useFetchQuotaStatus();
  const { save, saving, tenantId } = useUpdateUsagePolicy();

  const confirmedLimits = (quota?.data?.limits ?? {}) as Record<string, number>;
  const revision = quota?.data?.policy_revision;

  const [baseline, setBaseline] = useState<PolicyDraft>(() =>
    draftFromLimits(confirmedLimits),
  );
  const [draft, setDraft] = useState<PolicyDraft>(() =>
    draftFromLimits(confirmedLimits),
  );
  const [editing, setEditing] = useState(false);
  const [outcome, setOutcome] = useState<SaveOutcome>('idle');
  const [staleRevision, setStaleRevision] = useState<string | undefined>();

  // The confirmed values are the baseline. A refresh that lands while a draft is
  // open REBASES the comparison but never the draft: the reader keeps what they
  // typed, and the diff is recomputed against the new truth.
  useEffect(() => {
    const next = draftFromLimits(confirmedLimits);
    setBaseline(next);
    setDraft((previous) =>
      editing ? previous : next,
    );
    setStaleRevision((previous) => revision ?? previous);
  }, [revision, editing, quota]);

  const errors = useMemo(() => collectPolicyErrors(draft, baseline), [draft, baseline]);
  const dirty = isDraftDirty(baseline, draft);
  const patch = useMemo(() => buildPolicyPatch(baseline, draft), [baseline, draft]);
  const hasErrors = Object.keys(errors).length > 0;
  // A save is possible only on a resolved workspace with a known revision, a real
  // change, and values the STORAGE will accept.
  const canSave =
    !readOnly &&
    roleResolved &&
    Boolean(tenantId) &&
    Boolean(revision) &&
    dirty &&
    !hasErrors &&
    Object.keys(patch).length > 0 &&
    !saving;

  const handleChange = useCallback((field: keyof PolicyDraft) => (event: any) => {
    const value = event?.target?.value ?? '';
    setDraft((previous) => ({ ...previous, [field]: value }));
    setOutcome('idle');
  }, []);

  const handleEdit = useCallback(() => {
    setEditing(true);
    setOutcome('idle');
  }, []);

  const handleCancel = useCallback(() => {
    setDraft(baseline);
    setEditing(false);
    setOutcome('idle');
  }, [baseline]);

  const handleSave = useCallback(async () => {
    if (!canSave || !revision) {
      return;
    }
    const attempted = revision;
    try {
      const body = await save({ patch, revision: attempted });
      if (isPolicyConflict(body)) {
        // Offered again only after a successful reload: the point of the conflict
        // is that the reader is looking at a stale policy.
        setStaleRevision(attempted);
        setOutcome('conflict');
        return;
      }
      if (body?.code !== 0) {
        setOutcome('unknown');
        return;
      }
      setEditing(false);
      const refreshed = await refetch();
      setOutcome(refreshed?.error ? 'stale-after-save' : 'idle');
    } catch {
      // A timeout or a dropped connection: the write may or may not have landed.
      setOutcome('unknown');
    }
  }, [canSave, patch, refetch, revision, save]);

  const handleReload = useCallback(async () => {
    const refreshed = await refetch();
    if (!refreshed?.error) {
      setOutcome('idle');
    }
  }, [refetch]);

  if (!roleResolved) {
    return (
      <div className="p-4">
        <CardSkeleton />
      </div>
    );
  }

  if (readOnly) {
    return (
      <div className="p-4">
        <ComingDataPanel
          testId="usage-policy-not-authorized"
          tone="unavailable"
          titleKey="usage.subsectionNotAuthorizedTitle"
          descriptionKey="usage.subsectionNotAuthorizedDescription"
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4" data-testid="team-usage-policy">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h3 className="text-sm text-text-primary">{t('usage.policyTitle')}</h3>
          <p className="text-xs text-text-secondary">
            {t('usage.policyDescription')}
          </p>
        </div>

        <div className="flex items-center gap-2">
          {!editing ? (
            <Button
              size="sm"
              className="h-8 rounded-[2px] px-3 text-xs"
              disabled={loading || !quota?.data}
              onClick={handleEdit}
              data-testid="usage-policy-edit"
            >
              {t('usage.policyEdit')}
            </Button>
          ) : (
            <>
              <Button
                variant="ghost"
                size="sm"
                className="h-8 rounded-[2px] px-3 text-xs"
                disabled={saving}
                onClick={handleCancel}
                data-testid="usage-policy-cancel"
              >
                {t('usage.policyCancel')}
              </Button>
              <Button
                size="sm"
                className="h-8 rounded-[2px] px-3 text-xs"
                disabled={!canSave}
                onClick={handleSave}
                data-testid="usage-policy-save"
              >
                {saving ? t('usage.policySaving') : t('usage.policySave')}
              </Button>
            </>
          )}
        </div>
      </div>

      {outcome !== 'idle' && (
        <div
          className={cn(
            'ceramic-relief flex flex-col gap-2 rounded-[2px] p-3',
            outcome === 'conflict' && 'border border-state-warning',
          )}
          data-testid={`usage-policy-outcome-${outcome}`}
        >
          <p className="text-sm text-text-primary">
            {t(`usage.policyOutcome_${outcome}Title`)}
          </p>
          <p className="text-xs text-text-secondary">
            {t(`usage.policyOutcome_${outcome}Description`)}
          </p>
          {(outcome === 'conflict' || outcome === 'stale-after-save') && (
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={handleReload}
                data-testid="usage-policy-reload"
              >
                {t('usage.policyReload')}
              </Button>
              {outcome === 'conflict' && (
                <span className="text-xs text-text-disabled">
                  {t('usage.policyConflictReview', {
                    fields: Object.keys(patch)
                      .map((field) => t(POLICY_FIELD_LABEL_KEYS[field as never]))
                      .join(', '),
                  })}
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {loading && !quota ? (
        <CardSkeleton />
      ) : quota?.data ? (
        <>
          <div className="ceramic-relief flex flex-col rounded-[2px] p-3">
            <span className="pb-2 text-sm text-text-primary">
              {t('usage.policyPerMemberTitle')}
            </span>
            <LimitStandingList quota={quota} />
            {/* The exemption is the server's answer and is shown even while
                editing: an exempt manager must never be shown a limit they can
                fail to meet. */}
            {quota.data.subject?.exempt === true && (
              <p className="pt-2 text-xs text-state-warning" data-testid="usage-policy-exempt">
                {t('usage.policyExemptNotice')}
              </p>
            )}
          </div>

          {editing && (
            <div
              className="ceramic-relief flex flex-col gap-3 rounded-[2px] p-3"
              data-testid="usage-policy-form"
            >
              <span className="text-sm text-text-primary">
                {t('usage.policyFormTitle')}
              </span>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {POLICY_LIMIT_FIELDS.map((field) => (
                  <label key={field} className="flex flex-col gap-1">
                    <span className="text-xs text-text-secondary">
                      {t(POLICY_FIELD_LABEL_KEYS[field])}
                    </span>
                    <Input
                      inputMode="numeric"
                      value={draft[field]}
                      onChange={handleChange(field)}
                      disabled={saving}
                      aria-invalid={Boolean(errors[field])}
                      data-testid={`usage-policy-input-${field}`}
                    />
                    {errors[field] ? (
                      <span className="text-xs text-state-error">
                        {t(`usage.policyFieldError_${errors[field]}`)}
                      </span>
                    ) : (
                      <span className="text-xs text-text-disabled">
                        {field.startsWith('calls')
                          ? t('usage.policyFieldHintCalls')
                          : t('usage.policyFieldHintTokens')}
                      </span>
                    )}
                  </label>
                ))}
              </div>
              {!dirty && (
                <p className="text-xs text-text-disabled">
                  {t('usage.policyNoChanges')}
                </p>
              )}
              {outcome === 'conflict' && (
                <p className="text-xs text-state-warning">
                  {t('usage.policyConflictNeedsReload', {
                    revision: staleRevision ?? '',
                  })}
                </p>
              )}
            </div>
          )}
        </>
      ) : (
        <ReadModelNotice
          testId="usage-policy-unavailable"
          failed={Boolean(error)}
          onRetry={refetch}
        />
      )}
    </div>
  );
}

export default UsagePolicySection;
