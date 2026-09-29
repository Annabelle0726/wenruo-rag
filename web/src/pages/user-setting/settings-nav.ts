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
 * The Settings information architecture, as DATA.
 *
 * It is a model rather than a JSX list so the hierarchy - which section owns
 * which destination, which destinations are administrative, and which one only
 * exists when the data justifies it - can be asserted in a test instead of being
 * inferred from a rendered rail.
 *
 * Every child is a real ROUTE: the rail highlights the active child inside the
 * active parent, and the page a child names is reachable by URL. Headings inside
 * a page body are NOT navigation and are not modelled here.
 *
 * The path segments are literals rather than `Routes.*` lookups on purpose:
 * importing `@/routes` executes `createBrowserRouter` at module scope, which needs
 * a DOM, so every consumer of this model - including a Node test - would drag the
 * whole router in. `settings-nav.test.ts` checks these literals against
 * `routes.tsx` SOURCE, so they cannot drift from the real route table.
 */
export interface ISettingsNavChild {
  /** Absolute path, so the rail can navigate and match without re-deriving it. */
  path: string;
  labelKey: string;
  testId: string;
  /** Rendered only for a role the server reports as OWNER or ADMIN. */
  adminOnly?: boolean;
}

export interface ISettingsNavSection {
  /** The section's own destination. */
  path: string;
  labelKey: string;
  testId: string;
  children: ISettingsNavChild[];
}

/** The route segments this model builds from; verified against `routes.tsx`. */
export const SETTINGS_ROUTE_SEGMENTS = {
  userSetting: '/user-setting',
  model: '/model',
  team: '/team',
  usage: '/usage',
  profile: '/profile',
} as const;

const base = SETTINGS_ROUTE_SEGMENTS.userSetting;
const MODEL = SETTINGS_ROUTE_SEGMENTS.model;
const TEAM = SETTINGS_ROUTE_SEGMENTS.team;
const USAGE = SETTINGS_ROUTE_SEGMENTS.usage;
const PROFILE = SETTINGS_ROUTE_SEGMENTS.profile;

export const SETTINGS_PATHS = {
  model: `${base}${MODEL}`,
  modelManaged: `${base}${MODEL}/managed`,
  modelPrivate: `${base}${MODEL}/private`,
  modelUnclassified: `${base}${MODEL}/unclassified`,
  team: `${base}${TEAM}`,
  teamMembers: `${base}${TEAM}/members`,
  teamUsagePolicy: `${base}${TEAM}/usage-policy`,
  teamDepartments: `${base}${TEAM}/departments`,
  usage: `${base}${USAGE}`,
  usageMy: `${base}${USAGE}/my`,
  usageWorkspace: `${base}${USAGE}/workspace`,
  usageProviderHealth: `${base}${USAGE}/provider-health`,
  usageRetrievalHealth: `${base}${USAGE}/retrieval-health`,
  profile: `${base}${PROFILE}`,
} as const;

export interface ISettingsNavOptions {
  /**
   * How many configured providers could not be classified as a managed API or a
   * private endpoint. The Unclassified destination exists ONLY when there are
   * such providers: an empty category is a destination that can never show
   * anything, and inventing it would suggest the console knows something it does
   * not.
   */
  unclassifiedProviderCount?: number;
}

export const buildSettingsNav = (
  options: ISettingsNavOptions = {},
): ISettingsNavSection[] => {
  const sections: ISettingsNavSection[] = [
    {
      path: SETTINGS_PATHS.model,
      labelKey: 'setting.model',
      testId: 'settings-nav-model-providers',
      children: [
        {
          path: SETTINGS_PATHS.model,
          labelKey: 'setting.modelAll',
          testId: 'settings-subnav-model-all',
        },
        {
          path: SETTINGS_PATHS.modelManaged,
          labelKey: 'setting.modelManagedApi',
          testId: 'settings-subnav-model-managed',
        },
        {
          path: SETTINGS_PATHS.modelPrivate,
          labelKey: 'setting.modelPrivateEndpoint',
          testId: 'settings-subnav-model-private',
        },
      ],
    },
    {
      path: SETTINGS_PATHS.team,
      labelKey: 'setting.team',
      testId: 'settings-nav-team',
      children: [
        {
          path: SETTINGS_PATHS.teamMembers,
          labelKey: 'setting.teamMembersAndRoles',
          testId: 'settings-subnav-team-members',
        },
        {
          path: SETTINGS_PATHS.teamUsagePolicy,
          labelKey: 'setting.usagePolicy',
          testId: 'settings-subnav-team-usage-policy',
        },
        {
          path: SETTINGS_PATHS.teamDepartments,
          labelKey: 'setting.teamDepartments',
          testId: 'settings-subnav-team-departments',
        },
      ],
    },
    {
      path: SETTINGS_PATHS.usage,
      labelKey: 'setting.usageOperations',
      testId: 'settings-nav-usage-operations',
      children: [
        {
          path: SETTINGS_PATHS.usageMy,
          labelKey: 'usage.myUsage',
          testId: 'settings-subnav-usage-my',
        },
        {
          path: SETTINGS_PATHS.usageWorkspace,
          labelKey: 'usage.workspaceAnalytics',
          testId: 'settings-subnav-usage-workspace',
          adminOnly: true,
        },
        {
          path: SETTINGS_PATHS.usageProviderHealth,
          labelKey: 'usage.providerHealth',
          testId: 'settings-subnav-usage-provider-health',
          adminOnly: true,
        },
        {
          path: SETTINGS_PATHS.usageRetrievalHealth,
          labelKey: 'usage.retrievalHealth',
          testId: 'settings-subnav-usage-retrieval-health',
          adminOnly: true,
        },
      ],
    },
    {
      path: SETTINGS_PATHS.profile,
      labelKey: 'setting.profile',
      testId: 'settings-nav-profile',
      children: [],
    },
  ];

  if ((options.unclassifiedProviderCount ?? 0) > 0) {
    // Rendered inside its own group, after the two real categories.
    sections[0].children.push({
      path: SETTINGS_PATHS.modelUnclassified,
      labelKey: 'setting.modelUnclassified',
      testId: 'settings-subnav-model-unclassified',
    });
  }

  return sections;
};

/**
 * The child of `section` that the current path belongs to, or null.
 *
 * The LONGEST matching child wins, so `/model/managed` selects "Managed API" and
 * not the `/model` "all providers" entry that prefixes it. A path that matches no
 * child belongs to the section itself, which is what keeps the parent's own
 * destination (the existing model management page) identifiable.
 */
export const matchActiveChild = (
  section: ISettingsNavSection,
  pathname: string,
): ISettingsNavChild | null => {
  const matches = section.children.filter(
    (child) => pathname === child.path || pathname.startsWith(`${child.path}/`),
  );
  if (matches.length === 0) {
    return null;
  }
  return matches.reduce((longest, child) =>
    child.path.length > longest.path.length ? child : longest,
  );
};

/** The section the current path belongs to, or null outside Settings. */
export const matchActiveSection = (
  sections: ISettingsNavSection[],
  pathname: string,
): ISettingsNavSection | null => {
  const matches = sections.filter(
    (section) =>
      pathname === section.path || pathname.startsWith(`${section.path}/`),
  );
  if (matches.length === 0) {
    return null;
  }
  return matches.reduce((longest, section) =>
    section.path.length > longest.path.length ? section : longest,
  );
};
