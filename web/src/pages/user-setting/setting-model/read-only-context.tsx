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

import { createContext, FC, ReactNode, useContext } from 'react';

/**
 * Whether the model-settings subtree is read-only for the current user.
 *
 * A tenant member who is neither OWNER nor ADMIN may browse the tenant's
 * providers, instances and default models but may not change them: every
 * mutating model endpoint is admin-only on the server
 * (`@require_tenant_admin`), so an editable form here would only produce
 * 403s. This context carries the flag down to the leaves that own an
 * affordance (form fields, Save, delete, verify, model actions) instead of
 * threading a prop through five component layers.
 *
 * It is a UI affordance only and must never be treated as the guard - the
 * server decides authoritatively.
 */
const ModelSettingsReadOnlyContext = createContext(false);

export const ModelSettingsReadOnlyProvider: FC<{
  readOnly: boolean;
  children: ReactNode;
}> = ({ readOnly, children }) => (
  <ModelSettingsReadOnlyContext.Provider value={readOnly}>
    {children}
  </ModelSettingsReadOnlyContext.Provider>
);

export const useModelSettingsReadOnly = () =>
  useContext(ModelSettingsReadOnlyContext);
