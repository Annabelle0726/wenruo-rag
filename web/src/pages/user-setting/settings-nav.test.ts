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

import fs from 'fs';
import path from 'path';

import {
  buildSettingsNav,
  matchActiveChild,
  matchActiveSection,
  SETTINGS_PATHS,
  SETTINGS_ROUTE_SEGMENTS,
} from './settings-nav';

describe('the path literals match the real route table', () => {
  // The model cannot import `@/routes` (it builds a browser router at module
  // scope), so the segments are literals. This is the check that keeps them from
  // drifting: the route enum is read as SOURCE, without executing it.
  const source = fs.readFileSync(
    path.resolve(__dirname, '..', '..', 'routes.tsx'),
    'utf8',
  );

  const routeValue = (name: string): string | undefined =>
    source.match(new RegExp(`\\b${name} = '([^']+)'`))?.[1];

  it.each([
    ['userSetting', 'UserSetting'],
    ['model', 'Model'],
    ['team', 'Team'],
    ['usage', 'Usage'],
    ['profile', 'Profile'],
  ])('%s matches Routes.%s', (segment, route) => {
    expect(SETTINGS_ROUTE_SEGMENTS[segment as 'model']).toBe(routeValue(route));
  });

  it('registers every child destination as a real route', () => {
    const sections = buildSettingsNav({ unclassifiedProviderCount: 1 });
    const missing = sections
      .flatMap((section) => section.children.map((child) => child.path))
      .filter((childPath) => !source.includes(childPath.replace('/user-setting', '')))
      .filter((childPath) => !source.includes(childPath));

    expect(missing).toEqual([]);
  });
});

describe('the Settings information architecture is a real two-level tree', () => {
  const sections = buildSettingsNav();

  it('lists the four sections in console order', () => {
    expect(sections.map((section) => section.path)).toEqual([
      SETTINGS_PATHS.model,
      SETTINGS_PATHS.team,
      SETTINGS_PATHS.usage,
      SETTINGS_PATHS.profile,
    ]);
  });

  it('gives every operating section a second level, and Profile none', () => {
    expect(sections[0].children.map((child) => child.path)).toEqual([
      SETTINGS_PATHS.model,
      SETTINGS_PATHS.modelManaged,
      SETTINGS_PATHS.modelPrivate,
    ]);
    expect(sections[1].children.map((child) => child.path)).toEqual([
      SETTINGS_PATHS.teamMembers,
      SETTINGS_PATHS.teamUsagePolicy,
      SETTINGS_PATHS.teamDepartments,
    ]);
    expect(sections[2].children.map((child) => child.path)).toEqual([
      SETTINGS_PATHS.usageMy,
      SETTINGS_PATHS.usageWorkspace,
      SETTINGS_PATHS.usageProviderHealth,
      SETTINGS_PATHS.usageRetrievalHealth,
    ]);
    // Profile keeps its own page and gains no invented subsection.
    expect(sections[3].children).toEqual([]);
  });

  it('marks exactly the workspace-wide usage destinations as administrative', () => {
    const usage = sections[2];
    const adminOnly = usage.children
      .filter((child) => child.adminOnly)
      .map((child) => child.path);

    expect(adminOnly).toEqual([
      SETTINGS_PATHS.usageWorkspace,
      SETTINGS_PATHS.usageProviderHealth,
      SETTINGS_PATHS.usageRetrievalHealth,
    ]);
    // My Usage is every member's, so it must never be gated.
    expect(
      usage.children.find((child) => child.path === SETTINGS_PATHS.usageMy)
        ?.adminOnly,
    ).toBeFalsy();
  });

  it('shows the Unclassified destination ONLY when a provider needs it', () => {
    const withoutProviders = buildSettingsNav({ unclassifiedProviderCount: 0 });
    const withProviders = buildSettingsNav({ unclassifiedProviderCount: 2 });

    expect(
      withoutProviders[0].children.some(
        (child) => child.path === SETTINGS_PATHS.modelUnclassified,
      ),
    ).toBe(false);
    expect(
      withProviders[0].children.some(
        (child) => child.path === SETTINGS_PATHS.modelUnclassified,
      ),
    ).toBe(true);
  });

  it('gives every destination a distinct label key and test id', () => {
    const labelKeys = sections.flatMap((section) => [
      section.labelKey,
      ...section.children.map((child) => child.labelKey),
    ]);
    const testIds = sections.flatMap((section) => [
      section.testId,
      ...section.children.map((child) => child.testId),
    ]);

    expect(new Set(labelKeys).size).toBe(labelKeys.length);
    expect(new Set(testIds).size).toBe(testIds.length);
  });
});

describe('active-section and active-child matching', () => {
  const sections = buildSettingsNav({ unclassifiedProviderCount: 1 });

  it('selects the longest matching child, not the prefixing parent entry', () => {
    const model = sections[0];

    expect(matchActiveChild(model, SETTINGS_PATHS.modelManaged)?.path).toBe(
      SETTINGS_PATHS.modelManaged,
    );
    // The section's own page selects the "all providers" child, which IS `/model`.
    expect(matchActiveChild(model, SETTINGS_PATHS.model)?.path).toBe(
      SETTINGS_PATHS.model,
    );
    expect(matchActiveChild(model, SETTINGS_PATHS.modelUnclassified)?.path).toBe(
      SETTINGS_PATHS.modelUnclassified,
    );
  });

  it('ties every Team subsection to the Team section', () => {
    Object.values({
      members: SETTINGS_PATHS.teamMembers,
      policy: SETTINGS_PATHS.teamUsagePolicy,
      departments: SETTINGS_PATHS.teamDepartments,
    }).forEach((path) => {
      expect(matchActiveSection(sections, path)?.path).toBe(SETTINGS_PATHS.team);
    });
  });

  it('does not confuse a Model path with a Team path', () => {
    // `/model` and `/team` share no prefix, but `/usage` must not swallow them.
    expect(matchActiveSection(sections, SETTINGS_PATHS.usageWorkspace)?.path).toBe(
      SETTINGS_PATHS.usage,
    );
    expect(matchActiveSection(sections, SETTINGS_PATHS.modelPrivate)?.path).toBe(
      SETTINGS_PATHS.model,
    );
  });

  it('reports no section outside Settings', () => {
    expect(matchActiveSection(sections, '/datasets')).toBeNull();
  });
});
