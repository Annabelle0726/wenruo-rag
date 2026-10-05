export interface IUserInfo {
  access_token: string;
  avatar?: any;
  color_schema: string;
  create_date: string;
  create_time: number;
  email: string;
  id: string;
  is_active: string;
  is_anonymous: string;
  is_authenticated: string;
  is_superuser: boolean;
  language: string;
  last_login_time: string;
  login_channel: string;
  nickname: string;
  password: string;
  /** The caller's role in their active tenant. Absent on servers predating P1-05. */
  role?: string;
  status: string;
  timezone: string;
  update_date: string;
  update_time: number;
}

export type TaskExecutorElapsed = Record<string, number[]>;

export interface TaskExecutorHeartbeatItem {
  boot_at: string;
  current: null;
  done: number;
  failed: number;
  lag: number;
  name: string;
  now: string;
  pending: number;
}

export interface ISystemStatus {
  es: Es;
  storage: Storage;
  database: Database;
  redis: Redis;
  task_executor_heartbeat: Record<string, TaskExecutorHeartbeatItem[]>;
}

interface Redis {
  status: string;
  elapsed: number;
  error: string;
  pending: number;
}

export interface Storage {
  status: string;
  elapsed: number;
  error: string;
}

export interface Database {
  status: string;
  elapsed: number;
  error: string;
}

interface Es {
  status: string;
  elapsed: number;
  error: string;
  number_of_nodes: number;
  active_shards: number;
}

export interface ITenantUser {
  id: string;
  avatar: string;
  delta_seconds: number;
  /** The member's department in this workspace; absent when they have none. */
  department_id?: string | null;
  department_name?: string | null;
  email: string;
  is_active: string;
  is_anonymous: string;
  is_authenticated: string;
  is_superuser: boolean;
  /** True for the workspace owner, whose membership cannot be removed or reassigned. */
  is_owner?: boolean;
  nickname: string;
  role: string;
  status: string;
  /** Free-text job title, decided by the org chart rather than this system. */
  title?: string | null;
  update_date: string;
  user_id: string;
}

export interface IDepartment {
  id: string;
  name: string;
  parent_id?: string | null;
  status?: string;
  tenant_id?: string;
}

export interface ITenant {
  avatar: string;
  delta_seconds: number;
  email: string;
  /** True for the workspace the caller is currently operating in. */
  is_active?: boolean;
  /**
   * The workspace's own name. The row's identity is the workspace, while
   * `nickname`/`email`/`avatar` belong to its owner.
   */
  name?: string | null;
  nickname: string;
  role: string;
  tenant_id: string;
  update_date: string;
}
