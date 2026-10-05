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

import { classifyProviderEndpoint } from '@/constants/model-provider-endpoint';
import { useFetchConfiguredModels } from '@/hooks/use-model-provider-request';
import { useFetchUserInfo } from '@/hooks/use-user-setting-request';
import { canManageTenant } from '@/utils/tenant-role';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { buildSettingsNav, matchActiveChild, matchActiveSection } from '../settings-nav';

/**
 * The Settings rail's tree state.
 *
 * Three things it decides, in one place:
 *
 * 1. WHICH destinations this caller may be offered. An administrative child is
 *    dropped until the server REPORTS OWNER or ADMIN, so a member is never shown
 *    a destination whose first request would be refused - and a member never sees
 *    it at all afterwards. The client still is not the authority: the server
 *    re-checks the membership on every request.
 * 2. Whether the "Unclassified" destination exists, which depends on the
 *    configured providers rather than on the role.
 * 3. Which section is expanded: the active one always is, because a collapsed
 *    parent would hide the child the reader is currently on.
 */
export const useSettingsNav = () => {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { data: userInfo } = useFetchUserInfo();
  const { data: models } = useFetchConfiguredModels();
  const isManager = canManageTenant(userInfo?.role);

  const unclassifiedProviderCount = useMemo(
    () =>
      new Set(
        models
          .map((model) => model.provider_name)
          .filter(
            (providerName) =>
              classifyProviderEndpoint(providerName) === 'unclassified',
          ),
      ).size,
    [models],
  );

  const sections = useMemo(() => {
    const built = buildSettingsNav({ unclassifiedProviderCount });

    if (isManager) {
      return built;
    }

    return built.map((section) => ({
      ...section,
      children: section.children.filter((child) => !child.adminOnly),
    }));
  }, [isManager, unclassifiedProviderCount]);

  const activeSection = useMemo(
    () => matchActiveSection(sections, pathname),
    [pathname, sections],
  );
  const activeChild = useMemo(
    () => (activeSection ? matchActiveChild(activeSection, pathname) : null),
    [activeSection, pathname],
  );

  const [expandedPaths, setExpandedPaths] = useState<string[]>([]);

  // The active parent is always expanded; the reader may additionally open any
  // other one, and closing the active parent is not offered.
  useEffect(() => {
    const activePath = activeSection?.path;
    if (!activePath) {
      return;
    }
    setExpandedPaths((previous) =>
      previous.includes(activePath) ? previous : [...previous, activePath],
    );
  }, [activeSection?.path]);

  const toggleSection = useCallback((sectionPath: string) => {
    setExpandedPaths((previous) =>
      previous.includes(sectionPath)
        ? previous.filter((path) => path !== sectionPath)
        : [...previous, sectionPath],
    );
  }, []);

  const goTo = useCallback(
    (path: string) => {
      navigate(path);
    },
    [navigate],
  );

  return {
    sections,
    activeSection,
    activeChild,
    isManager,
    isExpanded: (sectionPath: string) => expandedPaths.includes(sectionPath),
    toggleSection,
    goTo,
  };
};

export default useSettingsNav;
