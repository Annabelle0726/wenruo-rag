import { TenantRole } from '@/pages/user-setting/constants';

/**
 * Whether a role may administer its tenant.
 *
 * Mirrors the server-side hierarchy OWNER > ADMIN > NORMAL, where OWNER implies
 * ADMIN, so a tenant owner needs no separate grant. The server decides this
 * authoritatively (`UserTenantService.can_manage_tenant`); this helper only
 * drives UI affordances and must never be treated as the guard.
 */
export const canManageTenant = (role?: string): boolean =>
  role === TenantRole.Owner || role === TenantRole.Admin;

/**
 * Whether the caller must be shown a read-only tenant surface.
 *
 * Drives every management affordance that belongs to the tenant rather than to
 * the person: the model configuration, the team roster's role and removal
 * controls, and the invitation button.
 *
 * Unlike {@link canManageTenant}, an unknown role resolves to `false` here: the
 * caller's privileges are genuinely unknown when the server does not report a
 * `role` (a server predating the field, or the Go backend), and presuming
 * "member" would lock a tenant owner out of their own configuration. The server
 * guards every mutation, so presuming editable can only produce a 108 the
 * caller would have hit anyway.
 */
export const isTenantMemberReadOnly = (role?: string): boolean =>
  Boolean(role) && !canManageTenant(role);

/**
 * Whether a management control may be RENDERED for this role.
 *
 * `isTenantMemberReadOnly` answers "must this surface be read-only", and its
 * `false` for an unreported role is deliberate — an unknown role must not lock an
 * owner out of their own workspace. That same answer is wrong as a render gate:
 * `GET /users/me` starts empty, so a NORMAL member would be shown the invite
 * button, the role pickers and the remove buttons for as long as it is in flight,
 * and every one of them is a request the server refuses. A control therefore
 * waits for a reported role; the server stays the authority either way.
 */
export const canRenderTenantControls = (role?: string): boolean =>
  Boolean(role) && !isTenantMemberReadOnly(role);

/**
 * Whether a role can be handed out by the role endpoint.
 *
 * Mirrors the server's `ASSIGNABLE_ROLES`: an owner is reached by creating a
 * workspace rather than by promotion, and `invite` belongs to the invitation
 * flow. A role outside this set has no entry in the role picker, so a control
 * bound to such a row would render blank.
 */
export const isAssignableTenantRole = (role?: string): boolean =>
  role === TenantRole.Admin || role === TenantRole.Normal;

export interface IRoleDisplayConfig {
  /**
   * Translation key, resolved by the caller with `t()`. Kept as a key rather
   * than a string so role labels stay translatable.
   */
  labelKey: string;
  /**
   * Badge classes built only from the semantic tokens declared in
   * `web/tailwind.config.js` (`bg-*`, `text-*`, `border-*`). Tailwind's default
   * palette must not appear here — see the colour-token rule in web/CLAUDE.md.
   */
  badgeClass: string;
}

const NEUTRAL_BADGE = 'bg-bg-card text-text-secondary border-border-default';

const ROLE_DISPLAY: Record<string, IRoleDisplayConfig> = {
  [TenantRole.Owner]: {
    labelKey: 'setting.roleOwner',
    badgeClass: 'bg-state-warning-5 text-state-warning border-border-button',
  },
  [TenantRole.Admin]: {
    labelKey: 'setting.roleAdmin',
    badgeClass: 'bg-accent-primary-5 text-accent-primary border-border-accent',
  },
  [TenantRole.Normal]: {
    labelKey: 'setting.roleMember',
    badgeClass: NEUTRAL_BADGE,
  },
  [TenantRole.Invite]: {
    labelKey: 'setting.roleInvite',
    badgeClass: NEUTRAL_BADGE,
  },
};

/**
 * Display config for a role.
 *
 * An unrecognised or absent role falls back to the neutral member styling. A
 * server predating the `role` field therefore renders a neutral tag rather than
 * claiming a privilege the caller may not hold.
 */
export const getRoleDisplayConfig = (role?: string): IRoleDisplayConfig =>
  (role ? ROLE_DISPLAY[role] : undefined) ?? {
    labelKey: 'setting.roleMember',
    badgeClass: NEUTRAL_BADGE,
  };
