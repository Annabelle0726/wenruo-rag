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
    setDraft((previous) => (editing ? previous : next));
    setStaleRevision((previous) => revision ?? previous);
  }, [revision, editing, quota]);

  const errors = useMemo(
    () => collectPolicyErrors(draft, baseline),
    [draft, baseline],
  );
  const dirty = isDraftDirty(baseline, draft);
  const patch = useMemo(
    () => buildPolicyPatch(baseline, draft),
    [baseline, draft],
  );
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

  const handleChange = useCallback(
    (field: keyof PolicyDraft) => (event: any) => {
      const value = event?.target?.value ?? '';
      setDraft((previous) => ({ ...previous, [field]: value }));
      setOutcome('idle');
    },
    [],
  );

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
      <div className="settings-body">
        <CardSkeleton />
      </div>
    );
  }

  if (readOnly) {
    return (
      <div className="settings-body">
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
    <div className="settings-body" data-testid="team-usage-policy">
      {/* One section frame for the whole policy: the title and its edit controls on
          the header line, the standing figures and the editor as two stacked blocks
          separated by a hairline. The previous shape put each block in its own
          raised card, which made three frames where one object exists. */}
      <section className="settings-section">
        <div className="settings-section-head">
          <div className="flex min-w-0 flex-col gap-0.5">
            <h3 className="settings-section-title">
              {t('usage.policyTitle')}
            </h3>
            <p className="settings-section-hint">
              {t('usage.policyDescription')}
            </p>
          </div>

          <div className="ms-auto flex shrink-0 items-center gap-2">
            {!editing ? (
              <Button
                size="sm"
                className="h-8 px-3 text-xs"
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
                  className="h-8 px-3 text-xs"
                  disabled={saving}
                  onClick={handleCancel}
                  data-testid="usage-policy-cancel"
                >
                  {t('usage.policyCancel')}
                </Button>
                <Button
                  size="sm"
                  className="h-8 px-3 text-xs"
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
              'settings-notice flex-col rounded-none border-0 border-b border-cable-hairline',
              outcome === 'conflict' && 'bg-state-warning-5',
            )}
            data-testid={`usage-policy-outcome-${outcome}`}
          >
            <p className="settings-notice-title">
              {t(`usage.policyOutcome_${outcome}Title`)}
            </p>
            <p className="settings-notice-body">
              {t(`usage.policyOutcome_${outcome}Description`)}
            </p>
            {(outcome === 'conflict' || outcome === 'stale-after-save') && (
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 px-3 text-xs"
                  onClick={handleReload}
                  data-testid="usage-policy-reload"
                >
                  {t('usage.policyReload')}
                </Button>
                {outcome === 'conflict' && (
                  <span className="settings-field-hint">
                    {t('usage.policyConflictReview', {
                      fields: Object.keys(patch)
                        .map((field) =>
                          t(POLICY_FIELD_LABEL_KEYS[field as never]),
                        )
                        .join(', '),
                    })}
                  </span>
                )}
              </div>
            )}
          </div>
        )}

        {loading && !quota ? (
          <div className="settings-section-body">
            <CardSkeleton />
          </div>
        ) : quota?.data ? (
          <div className="flex flex-col divide-y divide-cable-hairline">
            <div className="flex flex-col px-3.5 py-3">
              <span className="settings-section-title pb-1">
                {t('usage.policyPerMemberTitle')}
              </span>
              <LimitStandingList quota={quota} />
              {/* The exemption is the server's answer and is shown even while
                  editing: an exempt manager must never be shown a limit they can
                  fail to meet. */}
              {quota.data.subject?.exempt === true && (
                <p
                  className="pt-2 text-xs text-state-warning"
                  data-testid="usage-policy-exempt"
                >
                  {t('usage.policyExemptNotice')}
                </p>
              )}
            </div>

            {editing && (
              <div
                className="flex flex-col gap-3 px-3.5 py-3"
                data-testid="usage-policy-form"
              >
                <span className="settings-section-title">
                  {t('usage.policyFormTitle')}
                </span>
                {/* Two columns of the same field shape: label, control, then either
                    the error or the hint, so the controls share a baseline and a
                    message never resizes the row above it. */}
                <div className="grid grid-cols-1 gap-x-4 gap-y-3 md:grid-cols-2">
                  {POLICY_LIMIT_FIELDS.map((field) => (
                    <label key={field} className="settings-field">
                      <span className="settings-field-label">
                        {t(POLICY_FIELD_LABEL_KEYS[field])}
                      </span>
                      <Input
                        inputMode="numeric"
                        className="ceramic-field h-10 tabular-nums"
                        value={draft[field]}
                        onChange={handleChange(field)}
                        disabled={saving}
                        aria-invalid={Boolean(errors[field])}
                        data-testid={`usage-policy-input-${field}`}
                      />
                      {errors[field] ? (
                        <span className="settings-field-hint text-state-error">
                          {t(`usage.policyFieldError_${errors[field]}`)}
                        </span>
                      ) : (
                        <span className="settings-field-hint">
                          {field.startsWith('calls')
                            ? t('usage.policyFieldHintCalls')
                            : t('usage.policyFieldHintTokens')}
                        </span>
                      )}
                    </label>
                  ))}
                </div>
                {!dirty && (
                  <p className="settings-field-hint">
                    {t('usage.policyNoChanges')}
                  </p>
                )}
                {outcome === 'conflict' && (
                  <p className="settings-field-hint text-state-warning">
                    {t('usage.policyConflictNeedsReload', {
                      revision: staleRevision ?? '',
                    })}
                  </p>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="settings-section-body">
            <ReadModelNotice
              testId="usage-policy-unavailable"
              failed={Boolean(error)}
              onRetry={refetch}
            />
          </div>
        )}
      </section>
    </div>
  );
}

export default UsagePolicySection;
