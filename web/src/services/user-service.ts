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

import api from '@/utils/api';
import onboardingService from './onboarding-service';
import registerServer from '@/utils/register-server';
import request, { post } from '@/utils/request';

const {
  login,
  logout,
  register,
  setting,
  userInfo,
  tenantInfo,
  getSystemVersion,
  getSystemTokenList,
  removeSystemToken,
  createSystemToken,
  getSystemConfig,
  setLangfuseConfig,
} = api;

const methods = {
  login: {
    url: login,
    method: 'post',
  },
  logout: {
    url: logout,
    method: 'post',
  },
  register: {
    url: register,
    method: 'post',
  },
  setting: {
    url: setting,
    method: 'patch',
  },
  userInfo: {
    url: userInfo,
    method: 'get',
  },
  getTenantInfo: {
    url: tenantInfo,
    method: 'get',
  },
  getSystemVersion: {
    url: getSystemVersion,
    method: 'get',
  },
  listToken: {
    url: getSystemTokenList,
    method: 'get',
  },
  createToken: {
    url: createSystemToken,
    method: 'post',
  },
  removeToken: {
    url: removeSystemToken,
    method: 'delete',
  },
  getSystemConfig: {
    url: getSystemConfig,
    method: 'get',
  },
  setLangfuseConfig: {
    url: setLangfuseConfig,
    method: 'put',
  },
  getLangfuseConfig: {
    url: setLangfuseConfig,
    method: 'get',
  },
  deleteLangfuseConfig: {
    url: setLangfuseConfig,
    method: 'delete',
  },
} as const;

const userService = registerServer<keyof typeof methods>(methods, request);

export const getLoginChannels = () => request.get(api.loginChannels);
export const loginWithChannel = (channel: string) =>
  (window.location.href = api.loginChannel(channel));

export const listTenantUser = (tenantId: string) =>
  request.get(api.listTenantUser(tenantId));

/** The invitation's optional organisational attributes. */
export interface ITenantUserProfileInput {
  departmentId?: string | null;
  title?: string | null;
}

export const addTenantUser = (
  tenantId: string,
  email: string,
  role?: string,
  profile?: ITenantUserProfileInput,
) => {
  return onboardingService.invite(
    {
      tenantId,
      data: { email, role, departmentId: profile?.departmentId ?? null },
    },
    true,
  );
};

export const updateTenantUserProfile = ({
  tenantId,
  userId,
  departmentId,
  title,
}: {
  tenantId: string;
  userId: string;
  departmentId?: string | null;
  title?: string | null;
}) =>
  // umi-request again: the payload belongs under `data`.
  request.put(api.tenantUserProfile(tenantId, userId), {
    data: { departmentId, title },
  });

export const listDepartments = (tenantId: string) =>
  request.get(api.tenantDepartments(tenantId));

export const createDepartment = (tenantId: string, name: string) =>
  post(api.tenantDepartments(tenantId), { name });

export const renameDepartment = (
  tenantId: string,
  departmentId: string,
  name: string,
) =>
  request.put(api.tenantDepartment(tenantId, departmentId), { data: { name } });

export const deleteDepartment = (tenantId: string, departmentId: string) =>
  request.delete(api.tenantDepartment(tenantId, departmentId));

export const deleteTenantUser = ({
  tenantId,
  userId,
}: {
  tenantId: string;
  userId: string;
}) =>
  request.delete(api.deleteTenantUser(tenantId), {
    // camelCase reaches the API as `user_id`: the request interceptor converts
    // body keys before they go out.
    data: { userId },
  });

export const updateTenantUserRole = ({
  tenantId,
  userId,
  role,
}: {
  tenantId: string;
  userId: string;
  role: string;
}) =>
  // `request` is umi-request: the payload must sit under `data`, or the request
  // goes out with no body at all and the route's `validate_request("role")`
  // answers "required argument are missing: role".
  request.put(api.tenantUserRole(tenantId, userId), { data: { role } });

export const setActiveTenant = (tenantId: string) =>
  request.put(api.activeTenant, { data: { tenantId } });

export const listTenant = () => request.get(api.listTenant);

export const agreeTenant = (tenantId: string) =>
  request.patch(api.agreeTenant(tenantId));

export default userService;
