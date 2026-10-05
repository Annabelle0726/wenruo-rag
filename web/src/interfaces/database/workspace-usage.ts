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
 * The shape of the U1 usage read model (`/api/v1/tenants/<id>/usage/*`).
 *
 * These types mirror the server payload exactly, including the parts that exist
 * to keep the UI honest:
 *
 * - a cost figure is `number | null`, and `null` means NOT ESTABLISHED. It is
 *   never a zero charge, so it must render "Not available" rather than `$0.00`;
 * - `outstanding_*` is reserved BUDGET OCCUPANCY (in flight, or finished without
 *   reporting usage). It is not provider-reported usage and not proof that a
 *   call is still running;
 * - `cost_coverage` says how much of the scope carries pricing evidence at all.
 */

export type CostCoverage = 'complete' | 'partial' | 'unavailable';

export type UsageCostUnit = 'micro_usd' | string;

export interface IUsageAccounting {
  attempted_calls: number;
  settled_attempts: number;
  reserved_attempts: number;
  unsettled_attempts: number;
  outstanding_attempts: number;
  unrecognised_status_attempts: number;
  settled_tokens: number;
  outstanding_reserved_tokens: number;
  effective_tokens: number;
  settled_estimated_cost_micros: number | null;
  outstanding_reserved_cost_micros: number | null;
  cost_coverage: CostCoverage;
  settled_cost_coverage: CostCoverage;
  outstanding_cost_coverage: CostCoverage;
  cost_established_rows: number;
  cost_unestablished_rows: number;
  zero_usage_rows: number;
}

export interface IUsageCost {
  term: string;
  unit: UsageCostUnit;
  coverage: CostCoverage;
  settled_coverage: CostCoverage;
  outstanding_coverage: CostCoverage;
  notes: string[];
}

export interface IUsageScope {
  workspace_id: string;
  actor_user_id: string;
  role: string;
  workspace_wide: boolean;
  subject_user_id: string | null;
  timezone: string;
  limits_source: 'workspace_budget_row' | 'backend_defaults' | string;
}

export interface IUsagePeriod {
  kind?: 'day' | 'month';
  start_day?: string;
  end_day?: string;
  days?: number;
  start_month?: string;
  end_month?: string;
  months?: number;
  days_with_activity?: number;
  timezone?: string;
  timezones_in_scope?: string[];
}

export interface IUsageReconciliation {
  ledger_attempted_calls: number;
  counter_calls: number;
  calls_consistent: boolean;
  ledger_effective_tokens: number;
  counter_tokens: number;
  tokens_consistent: boolean;
  counter_rows: number;
  member_breakdown_attempted_calls?: number;
  member_breakdown_consistent?: boolean;
  semantics: string;
}

export interface IUsageEnvelope {
  view: string;
  scope: IUsageScope;
  period: IUsagePeriod;
  accounting: IUsageAccounting;
  cost: IUsageCost;
  notes: string[];
  reconciliation?: IUsageReconciliation;
  data?: Record<string, any>;
}

export interface IMemberUsageRow {
  user_id: string;
  nickname: string | null;
  name_available: boolean;
  live_member: boolean;
  role: string | null;
  accounting: IUsageAccounting;
}

export interface IMemberBreakdownData {
  members: IMemberUsageRow[];
  total_members: number;
  limit: number;
  offset: number;
  truncated: boolean;
  not_answered: string;
}

export interface IModelUsageRow {
  recorded_model_name: string | null;
  bucket: string;
  attribution: string;
  provider: string | null;
  key_instance: string | null;
  workload: string | null;
  accounting: IUsageAccounting;
}

export interface IRecordedModelBreakdownData {
  models: IModelUsageRow[];
  total_buckets: number;
  limit: number;
  offset: number;
  truncated: boolean;
  not_answered: string;
}

export interface ISeriesBucket {
  period: string;
  attempted_calls: number;
  accounting: IUsageAccounting;
}

export interface ISeriesData {
  buckets: ISeriesBucket[];
  granularity: string;
  zero_filled: string;
}

export interface IUsageLimitStanding {
  limit: number;
  enforced: boolean;
  used: number | null;
  used_available: boolean;
  exempt: boolean | null;
  remaining?: number | null;
  note?: string;
}

export interface IWorkspaceOccupancy {
  day: Record<string, number>;
  month: Record<string, number>;
  comparable_to_limits: boolean;
  note: string;
}

export interface IQuotaStatusData {
  limits: Record<string, number>;
  limits_scope: string;
  limits_source: string;
  zero_means_unlimited: string[];
  unit: string;
  token_unit: string;
  cost_unit: string;
  applies_to: string;
  subject: {
    user_id: string;
    role: string | null;
    live_member: boolean;
    exempt: boolean | null;
  };
  standing: Record<string, IUsageLimitStanding>;
  current_month_accounting: IUsageAccounting;
  workspace_occupancy: IWorkspaceOccupancy | null;
  not_answered: string;
}

/**
 * One member's report: the same envelope as every other view, with that member's
 * own rows behind it.
 *
 * `daily`/`monthly` are the existing series shape and `models` is the existing
 * recorded-model shape, so the panel renders them with the same components the
 * workspace sections use. Nothing here is recomputed on the client.
 */
export interface IMemberReportSubject {
  user_id: string;
  nickname: string | null;
  name_available: boolean;
  live_member: boolean;
  role: string | null;
}

export interface IMemberReportData {
  member: IMemberReportSubject;
  daily: ISeriesData;
  monthly: ISeriesData;
  models: IRecordedModelBreakdownData;
  not_answered: string;
}

/** Every usage view the U1 read model exposes. */
export type UsageView =
  | 'my_usage'
  | 'workspace_summary'
  | 'member_breakdown'
  | 'member_report'
  | 'daily_series'
  | 'monthly_series'
  | 'recorded_model_breakdown'
  | 'quota_status';

/** The seven read-only endpoints' request parameters. */
export interface IUsageRangeParams {
  start_day?: string;
  end_day?: string;
}

export interface IUsageMonthRangeParams {
  start_month?: string;
  end_month?: string;
}

export interface IUsagePageParams {
  limit?: number;
  offset?: number;
}
