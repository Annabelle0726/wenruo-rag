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

import message from '@/components/ui/message';
import { ResponseGetType } from '@/interfaces/database/base';
import { IToken } from '@/interfaces/database/chat';
import { ITenantInfo } from '@/interfaces/database/dataset';
import { ILangfuseConfig } from '@/interfaces/database/system';
import {
  IDepartment,
  ITenant,
  ITenantUser,
  IUserInfo,
} from '@/interfaces/database/user-setting';
import { ISetLangfuseConfigRequestBody } from '@/interfaces/request/system';
import { DEFAULT_LANGUAGE_CODE, supportedLanguages } from '@/locales/config';
import kbService from '@/services/knowledge-service';
import userService, {
  addTenantUser,
  agreeTenant,
  createDepartment,
  deleteDepartment,
  deleteTenantUser,
  listDepartments,
  listTenant,
  listTenantUser,
  renameDepartment,
  setActiveTenant,
  updateTenantUserProfile,
  updateTenantUserRole,
} from '@/services/user-service';
import { getActiveTenantId, setActiveTenantId } from '@/utils/active-tenant';
import { useIsGoBackend } from '@/utils/backend-variant';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useFetchDefaultModelDictionary } from './use-llm-request';

export const enum UserSettingApiAction {
  UserInfo = 'userInfo',
  TenantInfo = 'tenantInfo',
  SaveSetting = 'saveSetting',
  FetchManualSystemTokenList = 'fetchManualSystemTokenList',
  FetchSystemTokenList = 'fetchSystemTokenList',
  RemoveSystemToken = 'removeSystemToken',
  CreateSystemToken = 'createSystemToken',
  ListTenantUser = 'listTenantUser',
  AddTenantUser = 'addTenantUser',
  DeleteTenantUser = 'deleteTenantUser',
  UpdateTenantUserRole = 'updateTenantUserRole',
  UpdateTenantUserProfile = 'updateTenantUserProfile',
  ListDepartments = 'listDepartments',
  SetActiveTenant = 'setActiveTenant',
  ListTenant = 'listTenant',
  AgreeTenant = 'agreeTenant',
  SetLangfuseConfig = 'setLangfuseConfig',
  DeleteLangfuseConfig = 'deleteLangfuseConfig',
  ListPipelines = 'listPipelines',
  FetchLangfuseConfig = 'fetchLangfuseConfig',
}

/**
 * Every query key this domain owns.
 *
 * Reads and invalidations must reach the cache through this factory: they used
 * to be hand-written arrays on both sides, which is how a mutation ends up
 * invalidating a key nothing is cached under. The workspace-scoped keys carry
 * the workspace id, so switching workspace re-keys them rather than overwriting
 * one workspace's data with another's.
 */
export const UserSettingKeys = {
  userInfo: () => [UserSettingApiAction.UserInfo] as const,
  tenantInfo: () => [UserSettingApiAction.TenantInfo] as const,
  pipelineList: () => [UserSettingApiAction.ListPipelines] as const,
  systemTokenList: () => [UserSettingApiAction.FetchSystemTokenList] as const,
  /** Prefix form: the roster of every workspace. */
  tenantRoster: () => [UserSettingApiAction.ListTenantUser] as const,
  tenantRosterOf: (tenantId?: string) =>
    [UserSettingApiAction.ListTenantUser, tenantId] as const,
  joinedTenants: () => [UserSettingApiAction.ListTenant] as const,
  /** Prefix form: the departments of every workspace. */
  departments: () => [UserSettingApiAction.ListDepartments] as const,
  departmentsOf: (tenantId?: string) =>
    [UserSettingApiAction.ListDepartments, tenantId] as const,
  langfuseConfig: () => [UserSettingApiAction.FetchLangfuseConfig] as const,
};

export const useFetchUserInfo = (): ResponseGetType<IUserInfo> => {
  const { data, isFetching: loading } = useQuery({
    queryKey: UserSettingKeys.userInfo(),
    initialData: {},
    gcTime: 0,
    queryFn: async () => {
      const { data } = await userService.userInfo();

      if (data.code === 0) {
        const targetLng =
          supportedLanguages.find((lang) => lang.code === data.data.language)
            ?.code ?? DEFAULT_LANGUAGE_CODE;

        return Object.assign({}, data.data, {
          language: targetLng,
        });
      }

      return data.data ?? {};
    },
  });

  return { data, loading };
};

export const useFetchTenantData = (): ResponseGetType<ITenantInfo> => {
  const { data, isFetching: loading } = useQuery({
    queryKey: UserSettingKeys.tenantInfo(),
    initialData: {},
    gcTime: 0,
    queryFn: async () => {
      const { data: res } = await userService.getTenantInfo();
      if (res.code === 0) {
        // Mirror the server's workspace so the next request carries it as
        // `X-Tenant-Id` instead of waiting for a round trip to resolve.
        setActiveTenantId(res.data?.tenant_id);
        return res.data ?? {};
      }

      return res;
    },
  });
  return { data, loading };
};

export const useFetchTenantInfo = useFetchTenantData;

export const useSelectParserList = (): Array<{
  value: string;
  label: string;
}> => {
  const { data: tenantInfo } = useFetchTenantInfo();
  const { t } = useTranslation();

  // Detect backend runtime language (Go vs Python) so we can choose
  // the matching parser-list code path at runtime.
  const isGo = useIsGoBackend();

  // Go backend: fetch pipeline catalog dynamically.
  const { data: pipelineListData } = useQuery({
    queryKey: UserSettingKeys.pipelineList(),
    queryFn: async () => {
      const { data } = await kbService.listPipelines();
      return data;
    },
    staleTime: Infinity,
    enabled: isGo,
  });
  useFetchDefaultModelDictionary(true);

  const defaultParsers = useMemo(
    () => [
      { value: 'naive', label: t('knowledgeConfiguration.parserLabel.naive') },
      { value: 'qa', label: t('knowledgeConfiguration.parserLabel.qa') },
      {
        value: 'resume',
        label: t('knowledgeConfiguration.parserLabel.resume'),
      },
      {
        value: 'manual',
        label: t('knowledgeConfiguration.parserLabel.manual'),
      },
      { value: 'table', label: t('knowledgeConfiguration.parserLabel.table') },
      { value: 'paper', label: t('knowledgeConfiguration.parserLabel.paper') },
      { value: 'book', label: t('knowledgeConfiguration.parserLabel.book') },
      { value: 'laws', label: t('knowledgeConfiguration.parserLabel.laws') },
      {
        value: 'presentation',
        label: t('knowledgeConfiguration.parserLabel.presentation'),
      },
      {
        value: 'picture',
        label: t('knowledgeConfiguration.parserLabel.picture'),
      },
      { value: 'one', label: t('knowledgeConfiguration.parserLabel.one') },
      { value: 'audio', label: t('knowledgeConfiguration.parserLabel.audio') },
      { value: 'email', label: t('knowledgeConfiguration.parserLabel.email') },
      { value: 'tag', label: t('knowledgeConfiguration.parserLabel.tag') },
    ],
    [t],
  );

  const parserList = useMemo(() => {
    // Go backend: prefer the dynamic pipeline catalog from the API.
    // GET /api/v1/pipelines?type=builtin responds with
    // { code, data: { canvas: [{ id, title, description, filename }], total } }.
    if (isGo) {
      const pipelineList: Array<{
        id: string;
        title: string;
        description?: string;
        filename?: string;
      }> = pipelineListData?.data?.canvas ?? [];
      if (pipelineList.length > 0) {
        const labelFromAPI = (parserId: string, title: string) => {
          const key = `knowledgeConfiguration.parserLabel.${parserId}`;
          const translated = t(key);
          return translated !== key ? translated : title;
        };
        return pipelineList.map((item) => ({
          value: item.id,
          label: labelFromAPI(item.id, item.title),
        }));
      }
    }

    // Python backend (or fallback): use tenant-level parser_ids or
    // the hardcoded default parsers.
    const parserArray: Array<string> = tenantInfo?.parser_ids?.split(',') ?? [];
    const filteredArray = parserArray.filter((x) => x.trim() !== '');

    if (filteredArray.length === 0) {
      return defaultParsers;
    }

    return filteredArray.map((x) => {
      const arr = x.split(':');
      return { value: arr[0], label: arr[1] };
    });
  }, [tenantInfo, defaultParsers, isGo, pipelineListData, t]);

  return parserList;
};

export const useSaveSetting = (silent = false) => {
  const queryClient = useQueryClient();
  const { t } = useTranslation();
  const {
    data,
    isPending: loading,
    mutateAsync,
  } = useMutation({
    mutationKey: [UserSettingApiAction.SaveSetting],
    mutationFn: async (
      userInfo: { new_password: string } | Partial<IUserInfo>,
    ) => {
      const { data } = await userService.setting(userInfo);
      if (data.code === 0) {
        if (!silent) {
          message.success(t('message.modified'));
        }
        queryClient.invalidateQueries({ queryKey: UserSettingKeys.userInfo() });
      }
      return data?.code;
    },
  });

  return { data, loading, saveSetting: mutateAsync };
};

export const useFetchSystemVersion = () => {
  const [version, setVersion] = useState('');
  const [loading, setLoading] = useState(false);

  const fetchSystemVersion = useCallback(async () => {
    try {
      setLoading(true);
      const { data } = await userService.getSystemVersion();
      if (data.code === 0) {
        setVersion(data.data);
        setLoading(false);
      }
    } catch (error) {
      console.warn(error);
      setLoading(false);
    }
  }, []);

  return { fetchSystemVersion, version, loading };
};

export const useFetchManualSystemTokenList = () => {
  const {
    data,
    isPending: loading,
    mutateAsync,
  } = useMutation({
    mutationKey: [UserSettingApiAction.FetchManualSystemTokenList],
    mutationFn: async () => {
      const { data } = await userService.listToken();

      return data?.data ?? [];
    },
  });

  return { data, loading, fetchSystemTokenList: mutateAsync };
};

export const useFetchSystemTokenList = () => {
  const {
    data,
    isFetching: loading,
    refetch,
  } = useQuery<IToken[]>({
    queryKey: UserSettingKeys.systemTokenList(),
    initialData: [],
    gcTime: 0,
    queryFn: async () => {
      const { data } = await userService.listToken();

      return data?.data ?? [];
    },
  });

  return { data, loading, refetch };
};

export const useRemoveSystemToken = () => {
  const queryClient = useQueryClient();
  const { t } = useTranslation();

  const {
    data,
    isPending: loading,
    mutateAsync,
  } = useMutation({
    mutationKey: [UserSettingApiAction.RemoveSystemToken],
    mutationFn: async (token: string) => {
      const { data } = await userService.removeToken({}, token);
      if (data.code === 0) {
        message.success(t('message.deleted'));
        queryClient.invalidateQueries({
          queryKey: UserSettingKeys.systemTokenList(),
        });
      }
      return data?.data ?? [];
    },
  });

  return { data, loading, removeToken: mutateAsync };
};

export const useCreateSystemToken = () => {
  const queryClient = useQueryClient();

  const {
    data,
    isPending: loading,
    mutateAsync,
  } = useMutation({
    mutationKey: [UserSettingApiAction.CreateSystemToken],
    mutationFn: async (params: Record<string, any>) => {
      const { data } = await userService.createToken(params);
      if (data.code === 0) {
        queryClient.invalidateQueries({
          queryKey: UserSettingKeys.systemTokenList(),
        });
      }
      return data?.data ?? [];
    },
  });

  return { data, loading, createToken: mutateAsync };
};

export const useListTenantUser = () => {
  const { data: tenantInfo } = useFetchTenantInfo();
  const tenantId = tenantInfo.tenant_id;
  const {
    data,
    isFetching: loading,
    refetch,
  } = useQuery<ITenantUser[]>({
    queryKey: UserSettingKeys.tenantRosterOf(tenantId),
    initialData: [],
    gcTime: 0,
    enabled: !!tenantId,
    queryFn: async () => {
      const { data } = await listTenantUser(tenantId);

      return data?.data ?? [];
    },
  });

  return { data, loading, refetch };
};

export const useAddTenantUser = () => {
  const { data: tenantInfo } = useFetchTenantInfo();
  const queryClient = useQueryClient();
  const {
    data,
    isPending: loading,
    mutateAsync,
  } = useMutation({
    mutationKey: [UserSettingApiAction.AddTenantUser],
    // The invite dialog collects a department and a title as well; both belong
    // to the invitation, so they are forwarded instead of being dropped here.
    mutationFn: async ({
      email,
      role,
      departmentId,
      title,
    }: {
      email: string;
      role?: string;
      departmentId?: string | null;
      title?: string | null;
    }) => {
      const tenantId = tenantInfo.tenant_id;
      if (!tenantId) {
        // `/users/me/models` has not answered yet, so there is no workspace to
        // invite into: posting anyway would build `/tenants/undefined/users`.
        return undefined;
      }
      const { data } = await addTenantUser(tenantId, email, role, {
        departmentId,
        title,
      });
      // `data?.code`: a reply with no body leaves `data` undefined, and reading
      // `.code` off it would throw inside the mutation and surface as an
      // unhandled rejection rather than a refused invitation.
      if (data?.code === 0) {
        queryClient.invalidateQueries({
          queryKey: UserSettingKeys.tenantRoster(),
        });
      }
      return data;
    },
  });

  return { data, loading, addTenantUser: mutateAsync };
};

export const useDeleteTenantUser = () => {
  const { data: tenantInfo } = useFetchTenantInfo();
  const { data: userInfo } = useFetchUserInfo();
  const queryClient = useQueryClient();
  const { t } = useTranslation();

  const {
    data,
    isPending: loading,
    mutateAsync,
  } = useMutation({
    mutationKey: [UserSettingApiAction.DeleteTenantUser],
    mutationFn: async ({
      userId,
      tenantId,
    }: {
      userId: string;
      tenantId?: string;
    }) => {
      const targetTenantId = tenantId ?? tenantInfo.tenant_id;
      // Removing someone else is a roster edit; removing the caller is leaving
      // a workspace. Leaving the one they are operating in is a workspace
      // change: the server drops the stored selection with the membership, so
      // the client's header value has to follow.
      const leavingActiveWorkspace =
        userId === userInfo?.id && targetTenantId === getActiveTenantId();

      const { data } = await deleteTenantUser({
        tenantId: targetTenantId,
        userId,
      });
      if (data.code === 0) {
        message.success(t('message.deleted'));
        queryClient.invalidateQueries({
          queryKey: UserSettingKeys.tenantRoster(),
        });
        queryClient.invalidateQueries({
          queryKey: UserSettingKeys.joinedTenants(),
        });
        if (leavingActiveWorkspace) {
          setActiveTenantId(null);
          queryClient.invalidateQueries({
            queryKey: UserSettingKeys.tenantInfo(),
          });
        }
      }
      return data?.data ?? [];
    },
  });

  return { data, loading, deleteTenantUser: mutateAsync };
};

export const useListTenant = () => {
  const {
    data,
    isFetching: loading,
    refetch,
  } = useQuery<ITenant[]>({
    queryKey: UserSettingKeys.joinedTenants(),
    initialData: [],
    gcTime: 0,
    queryFn: async () => {
      const { data } = await listTenant();

      return data?.data ?? [];
    },
  });

  return { data, loading, refetch };
};

/**
 * Switch the active workspace.
 *
 * After the server accepts the switch, every cached query belongs to the
 * previous workspace, so the whole cache is dropped rather than invalidated
 * query by query: the model list, the roster and the datasets are all
 * workspace-scoped.
 */
export const useSetActiveTenant = () => {
  const queryClient = useQueryClient();
  const { t } = useTranslation();

  const { isPending: loading, mutateAsync } = useMutation({
    mutationKey: [UserSettingApiAction.SetActiveTenant],
    mutationFn: async (tenantId: string) => {
      const { data } = await setActiveTenant(tenantId);
      if (data.code === 0) {
        setActiveTenantId(tenantId);
        message.success(t('setting.switchedWorkspace'));
        await queryClient.invalidateQueries();
      }
      return data;
    },
  });

  return { loading, setActiveTenant: mutateAsync };
};

/**
 * The workspace's departments, flat.
 *
 * `parent_id` is in the payload so a tree can be rendered later; nothing here
 * assumes one.
 */
export const useListDepartments = () => {
  const { data: tenantInfo } = useFetchTenantInfo();
  const tenantId = tenantInfo.tenant_id;
  const {
    data,
    isFetching: loading,
    refetch,
  } = useQuery<IDepartment[]>({
    queryKey: UserSettingKeys.departmentsOf(tenantId),
    initialData: [],
    gcTime: 0,
    enabled: !!tenantId,
    queryFn: async () => {
      const { data } = await listDepartments(tenantId);
      return data?.data ?? [];
    },
  });

  return { data, loading, refetch };
};

/** Create, rename and delete departments. Manager-only on the server. */
export const useDepartmentMutations = () => {
  const { data: tenantInfo } = useFetchTenantInfo();
  const queryClient = useQueryClient();
  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: UserSettingKeys.departments(),
    });
  // The roster rows carry `department_name`, so a rename or a delete leaves them
  // showing a name that no longer exists until they are refetched too.
  const invalidateRoster = () =>
    queryClient.invalidateQueries({
      queryKey: UserSettingKeys.tenantRoster(),
    });

  const { isPending: creating, mutateAsync: create } = useMutation({
    mutationKey: [UserSettingApiAction.ListDepartments, 'create'],
    mutationFn: async (name: string) => {
      const { data } = await createDepartment(tenantInfo.tenant_id, name);
      if (data.code === 0) {
        await invalidate();
      }
      return data;
    },
  });

  const { isPending: renaming, mutateAsync: rename } = useMutation({
    mutationKey: [UserSettingApiAction.ListDepartments, 'rename'],
    mutationFn: async ({
      departmentId,
      name,
    }: {
      departmentId: string;
      name: string;
    }) => {
      const { data } = await renameDepartment(
        tenantInfo.tenant_id,
        departmentId,
        name,
      );
      if (data.code === 0) {
        await invalidate();
        await invalidateRoster();
      }
      return data;
    },
  });

  const { isPending: removing, mutateAsync: remove } = useMutation({
    mutationKey: [UserSettingApiAction.ListDepartments, 'delete'],
    mutationFn: async (departmentId: string) => {
      const { data } = await deleteDepartment(
        tenantInfo.tenant_id,
        departmentId,
      );
      if (data.code === 0) {
        await invalidate();
        // The roster rows carry the department name, so they are stale now.
        await invalidateRoster();
      }
      return data;
    },
  });

  return { creating, renaming, removing, create, rename, remove };
};

/** Move a member between departments, or retitle them. */
export const useUpdateTenantUserProfile = () => {
  const { data: tenantInfo } = useFetchTenantInfo();
  const queryClient = useQueryClient();

  const { isPending: loading, mutateAsync } = useMutation({
    mutationKey: [UserSettingApiAction.UpdateTenantUserProfile],
    mutationFn: async ({
      userId,
      departmentId,
      title,
    }: {
      userId: string;
      departmentId?: string | null;
      title?: string | null;
    }) => {
      const { data } = await updateTenantUserProfile({
        tenantId: tenantInfo.tenant_id,
        userId,
        departmentId,
        title,
      });
      if (data.code === 0) {
        queryClient.invalidateQueries({
          queryKey: UserSettingKeys.tenantRoster(),
        });
      }
      return data;
    },
  });

  return { loading, updateTenantUserProfile: mutateAsync };
};

export const useUpdateTenantUserRole = () => {
  const { data: tenantInfo } = useFetchTenantInfo();
  const queryClient = useQueryClient();

  const { isPending: loading, mutateAsync } = useMutation({
    mutationKey: [UserSettingApiAction.UpdateTenantUserRole],
    mutationFn: async ({
      userId,
      role,
      tenantId,
    }: {
      userId: string;
      role: string;
      tenantId?: string;
    }) => {
      const { data } = await updateTenantUserRole({
        tenantId: tenantId ?? tenantInfo.tenant_id,
        userId,
        role,
      });
      if (data.code === 0) {
        queryClient.invalidateQueries({
          queryKey: UserSettingKeys.tenantRoster(),
        });
        // A promotion can change who may manage the workspace, which is what
        // the joined-workspace list reports per row.
        queryClient.invalidateQueries({
          queryKey: UserSettingKeys.joinedTenants(),
        });
      }
      return data;
    },
  });

  return { loading, updateTenantUserRole: mutateAsync };
};

/**
 * Accept a pending invitation.
 *
 * Accepting is also a workspace switch - the server makes the invited workspace
 * the caller's active one - so the client has to follow. The stored
 * `X-Tenant-Id` is what makes the switch take effect on the next request, and
 * the tenant-info key is what the roster is keyed off: without refetching it,
 * the roster keeps its previous workspace's key and the page goes on showing
 * the workspace the caller just left.
 */
export const useAgreeTenant = () => {
  const queryClient = useQueryClient();
  const { t } = useTranslation();

  const {
    data,
    isPending: loading,
    mutateAsync,
  } = useMutation({
    mutationKey: [UserSettingApiAction.AgreeTenant],
    mutationFn: async (tenantId: string) => {
      const { data } = await agreeTenant(tenantId);
      if (data.code === 0) {
        message.success(t('message.operated'));
        setActiveTenantId(tenantId);
        queryClient.invalidateQueries({
          queryKey: UserSettingKeys.tenantInfo(),
        });
        queryClient.invalidateQueries({
          queryKey: UserSettingKeys.joinedTenants(),
        });
        queryClient.invalidateQueries({
          queryKey: UserSettingKeys.tenantRoster(),
        });
      }
      return data?.data ?? [];
    },
  });

  return { data, loading, agreeTenant: mutateAsync };
};

export const useSetLangfuseConfig = () => {
  const { t } = useTranslation();
  const {
    data,
    isPending: loading,
    mutateAsync,
  } = useMutation({
    mutationKey: [UserSettingApiAction.SetLangfuseConfig],
    mutationFn: async (params: ISetLangfuseConfigRequestBody) => {
      const { data } = await userService.setLangfuseConfig(params);
      if (data.code === 0) {
        message.success(t('message.operated'));
      }
      return data?.code;
    },
  });

  return { data, loading, setLangfuseConfig: mutateAsync };
};

export const useDeleteLangfuseConfig = () => {
  const { t } = useTranslation();
  const {
    data,
    isPending: loading,
    mutateAsync,
  } = useMutation({
    mutationKey: [UserSettingApiAction.DeleteLangfuseConfig],
    mutationFn: async () => {
      const { data } = await userService.deleteLangfuseConfig();
      if (data.code === 0) {
        if (data.data) {
          message.success(t('message.deleted'));
        } else {
          message.warning(t('message.noLangfuseConfigToDelete'));
        }
      }
      return data?.code;
    },
  });

  return { data, loading, deleteLangfuseConfig: mutateAsync };
};

export const useFetchLangfuseConfig = () => {
  const { data, isFetching: loading } = useQuery<ILangfuseConfig>({
    queryKey: UserSettingKeys.langfuseConfig(),
    gcTime: 0,
    queryFn: async () => {
      const { data } = await userService.getLangfuseConfig();

      return data?.data;
    },
  });

  return { data, loading };
};
